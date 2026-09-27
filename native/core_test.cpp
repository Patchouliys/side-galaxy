#include "side_galaxy_core.h"
#include <nlohmann/json.hpp>
#include <sqlite3.h>

#include <chrono>
#include <filesystem>
#include <future>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

using Json = nlohmann::json;

void require(bool condition, const std::string& message) {
    if (!condition) throw std::runtime_error(message);
}

class Fixture {
public:
    std::filesystem::path path = std::filesystem::temp_directory_path() /
        ("side-galaxy-core-test-" + std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()) + ".db");
    ~Fixture() {
        for (const auto& suffix : {"", "-wal", "-shm"}) {
            std::error_code ignored;
            std::filesystem::remove(path.string() + suffix, ignored);
        }
    }
    Json call(const std::string& operation, const Json& payload = Json::object()) const {
        char* raw = sg_core_call(path.string().c_str(), operation.c_str(), payload.dump().c_str());
        require(raw != nullptr, "Core returned allocation failure");
        std::string text(raw);
        sg_core_free(raw);
        return Json::parse(text);
    }
    Json good(const std::string& operation, const Json& payload = Json::object()) const {
        auto response = call(operation, payload);
        require(response.at("ok").get<bool>(), operation + ": " + response.dump());
        return response.at("value");
    }
    void bad(const std::string& operation, const Json& payload, const std::string& kind) const {
        auto response = call(operation, payload);
        require(!response.at("ok").get<bool>() && response.at("error").at("kind") == kind,
                operation + ": unexpected error " + response.dump());
    }
    void sql(const char* statement) const {
        sqlite3* database = nullptr;
        require(sqlite3_open(path.string().c_str(), &database) == SQLITE_OK, "Test SQLite open failed");
        const int code = sqlite3_exec(database, statement, nullptr, nullptr, nullptr);
        sqlite3_close(database);
        require(code == SQLITE_OK, "Test SQLite update failed");
    }
};

Json description(char generation = 'a') {
    return {{"protocol", 1}, {"name", "native test module"}, {"mode", "synthetic"},
            {"cpus", {0, 1, 2, 3}}, {"reserved_cpus", {0}}, {"memory_mib", 4096},
            {"capabilities", {"cpu-affinity", "memory-limit", "interference"}},
            {"templates", {"cpu-contention", "workload"}}, {"module_sha256", std::string(64, generation)},
            {"cleanup_scope", "process-group"}, {"memory_limit_required", false}};
}

Json plan(const Json& boards = Json::array({"alpha", "beta"})) {
    return {{"boards", boards}, {"template", "cpu-contention"}, {"cpus", {1}}, {"interference_cpus", {2}},
            {"memory_mib", 256}, {"duration_seconds", 1}, {"artifact_sha256", nullptr},
            {"arguments", Json::array()}, {"environment", Json::object()}, {"bandwidth_percent", nullptr}};
}

Json submission(const std::string& key, const Json& requested = plan(), char hash = 'b') {
    Json ids = Json::array();
    for (std::size_t i = 0; i < requested.at("boards").size(); ++i) ids.push_back(key + "-run-" + std::to_string(i));
    return {{"plan", requested}, {"plan_sha256", std::string(64, hash)}, {"key", key},
            {"batch_id", key + "-batch"}, {"run_ids", ids}, {"artifact_available", true}};
}

void heartbeat(const Fixture& fixture, const char* board, char generation = 'a') {
    fixture.good("heartbeat", {{"board_id", board}, {"heartbeat", {{"description", description(generation)},
                                                                  {"reload_ack", 0}, {"reload_error", nullptr}}}});
}

void enroll(Fixture& fixture) {
    require(fixture.good("init").at("initialized").get<bool>(), "Schema not initialized");
    for (const auto& board : {"alpha", "beta"}) {
        fixture.good("enroll", {{"data", {{"name", board}, {"board_profile", "generic"}, {"system_profile", "simulator"}}},
                                {"board_id", board}, {"token_hash", std::string(64, 'c')}, {"local", false}});
        heartbeat(fixture, board);
    }
}

Json completion(bool clean = true, char generation = 'a') {
    return {{"state", "succeeded"}, {"result", Json::object()},
            {"module_sha256", std::string(64, generation)}, {"cleanup_ok", clean}};
}

int main() {
    try {
        require(sg_core_abi_version() == 1, "Unexpected ABI version");
        Fixture fixture;
        enroll(fixture);
        auto boards = fixture.good("boards");
        require(boards.size() == 2 && !boards[0].contains("token_hash"), "Board output exposed token digest");
        require(fixture.good("agent_allowed", {{"board_id", "alpha"}, {"token_hash", std::string(64, 'c')}}).get<bool>(), "Valid agent rejected");
        require(!fixture.good("agent_allowed", {{"board_id", "beta"}, {"token_hash", std::string(64, 'd')}}).get<bool>(), "Invalid agent accepted");
        fixture.bad("heartbeat", {{"board_id", "missing"}, {"heartbeat", {{"description", description()}}}}, "not_found");

        auto invalid = submission("invalid", plan(Json::array({"alpha", "missing"})));
        fixture.bad("submit", invalid, "conflict");
        require(fixture.good("batches").empty(), "Partial batch admitted");
        invalid = submission("reserved");
        invalid["plan"]["cpus"] = {0};
        require(!fixture.good("preflight", invalid).at("valid").get<bool>(), "Reserved core admitted");
        invalid["plan"]["cpus"] = {1};
        invalid["plan"]["bandwidth_percent"] = 50;
        require(!fixture.good("preflight", invalid).at("valid").get<bool>(), "Unsupported bandwidth admitted");
        invalid["plan"]["cpus"] = {2};
        fixture.bad("preflight", invalid, "invalid");

        std::vector<std::future<Json>> futures;
        for (int i = 0; i < 8; ++i)
            futures.push_back(std::async(std::launch::async, [&fixture, i] {
                return fixture.call("submit", submission("parallel-" + std::to_string(i)));
            }));
        int winners = 0;
        Json winner;
        for (auto& future : futures) {
            auto response = future.get();
            if (response.at("ok").get<bool>()) { ++winners; winner = response.at("value"); }
            else require(response.at("error").at("kind") == "conflict", "Concurrent admission failed unexpectedly");
        }
        require(winners == 1 && fixture.good("batches").size() == 1, "Admission was not atomic under concurrent callers");
        const auto batch_id = winner.at("id").get<std::string>();
        const auto key = batch_id.substr(0, batch_id.size() - 6);
        require(fixture.good("submit", submission(key)).at("id") == batch_id, "Idempotent retry created another batch");
        fixture.bad("submit", submission(key, plan(), 'd'), "conflict");
        auto running = fixture.good("poll", {{"board_id", "alpha"}});
        require(running.at("claimed").get<bool>(), "First poll did not claim run");
        require(!fixture.good("poll", {{"board_id", "alpha"}}).at("claimed").get<bool>(), "Second poll claimed run twice");
        fixture.bad("board_action", {{"board_id", "alpha"}, {"action", "recover"}}, "conflict");
        fixture.good("cancel", {{"batch_id", batch_id}});
        require(fixture.good("poll", {{"board_id", "alpha"}}).at("state") == "cancelling", "Cancel released live lease");
        require(!fixture.good("preflight", submission("blocked")).at("valid").get<bool>(), "Cancellation released lease before acknowledgement");
        fixture.bad("finish", {{"board_id", "beta"}, {"run_id", running.at("id")}, {"completion", completion()}}, "not_found");
        fixture.bad("finish", {{"board_id", "alpha"}, {"run_id", running.at("id")}, {"completion", completion(true, 'd')}}, "conflict");
        auto failed = fixture.good("finish", {{"board_id", "alpha"}, {"run_id", running.at("id")}, {"completion", completion(false)}});
        require(failed.at("state") == "failed", "Unconfirmed cleanup did not fail run");
        require(fixture.good("boards")[0].at("status") == "quarantined", "Unconfirmed cleanup did not quarantine board");
        heartbeat(fixture, "alpha");
        require(!fixture.good("preflight", submission("still-blocked")).at("valid").get<bool>(), "Heartbeat cleared quarantine");
        fixture.good("board_action", {{"board_id", "alpha"}, {"action", "recover"}});
        require(fixture.good("preflight", submission("free")).at("valid").get<bool>(), "Explicit recovery did not free board");

        auto expiring = fixture.good("submit", submission("expiry"));
        running = fixture.good("poll", {{"board_id", "alpha"}});
        fixture.sql("UPDATE boards SET seen=0 WHERE id='alpha'");
        auto expired = fixture.good("batch", {{"batch_id", expiring.at("id")}});
        require(expired.at("runs")[0].at("state") == "lost", "Expired running run did not become lost");
        require(fixture.good("finish", {{"board_id", "alpha"}, {"run_id", running.at("id")}, {"completion", completion()}}).at("state") == "lost", "Late completion changed lost evidence");
        heartbeat(fixture, "alpha");
        fixture.good("cancel", {{"batch_id", expiring.at("id")}});
        fixture.good("board_action", {{"board_id", "alpha"}, {"action", "recover"}});

        auto changed = fixture.good("submit", submission("module"));
        heartbeat(fixture, "alpha", 'd');
        require(fixture.good("poll", {{"board_id", "alpha"}}).is_null(), "Changed module started a pinned old generation");
        require(fixture.good("batch", {{"batch_id", changed.at("id")}}).at("runs")[0].at("state") == "failed", "Changed module did not fail queued run");
        fixture.good("cancel", {{"batch_id", changed.at("id")}});
        heartbeat(fixture, "alpha");

        auto artifact_plan = plan(Json::array({"alpha"}));
        artifact_plan["template"] = "workload";
        artifact_plan["interference_cpus"] = Json::array();
        artifact_plan["artifact_sha256"] = std::string(64, 'e');
        artifact_plan["duration_seconds"] = 86400;
        auto artifact = submission("artifact", artifact_plan);
        artifact["artifact_available"] = false;
        require(!fixture.good("preflight", artifact).at("valid").get<bool>(), "Unavailable artifact admitted");
        artifact["artifact_available"] = true;
        fixture.good("submit", artifact);
        running = fixture.good("poll", {{"board_id", "alpha"}});
        auto finished = completion();
        finished["result"] = {{"outputs", {{{"path", "result.txt"}, {"size", 0}, {"sha256", std::string(64, 'f')}, {"data_base64", ""}}}},
                              {"synthetic", true}, {"custom_evidence", {{"generation", 42}}}};
        auto view = fixture.good("finish", {{"board_id", "alpha"}, {"run_id", running.at("id")}, {"completion", finished}});
        require(!view.at("result").at("outputs")[0].contains("data_base64"), "Result listing includes embedded file bytes");
        require(view.at("result").at("custom_evidence").at("generation") == 42, "Custom evidence was lost");
        fixture.good("board_action", {{"board_id", "alpha"}, {"action", "reload"}});
        require(fixture.good("boards")[0].at("reload_requested") == 1, "Reload counter not updated");
        fixture.bad("board_action", {{"board_id", "alpha"}, {"action", "unknown"}}, "invalid");
        fixture.bad("unknown", Json::object(), "invalid");
        fixture.bad("submit", Json::object(), "invalid");
        fixture.good("init");
        require(fixture.good("batches").size() == 4, "Reinitializing schema changed existing history");
        Fixture compatibility;
        enroll(compatibility);
        auto portable = submission("portable", artifact_plan);
        portable["artifact_requirements"] = {{"architectures", {"aarch64"}}, {"os", "linux"}, {"commands", {"cc"}}};
        auto checked = compatibility.good("preflight", portable);
        require(!checked.at("valid").get<bool>() && checked.at("errors")[0].at("reasons").dump().find("unknown") != std::string::npos,
                "Missing environment discovery must fail closed");
        auto target = description();
        target["execution_environment"] = {{"architecture", "aarch64"}, {"os", "linux"},
                                            {"commands", {"cc", "python3"}}, {"commands_complete", true}};
        auto report = [&](const char* board) {
            compatibility.good("heartbeat", {{"board_id", board}, {"heartbeat", {{"description", target}}}});
        };
        report("alpha");
        require(compatibility.good("preflight", portable).at("valid").get<bool>(), "Compatible environment rejected");
        target["execution_environment"]["architecture"] = "x86_64";
        report("beta");
        auto mixed = portable;
        mixed["plan"]["boards"] = {"alpha", "beta"};
        mixed["run_ids"] = {"portable-alpha", "portable-beta"};
        compatibility.bad("submit", mixed, "conflict");
        require(compatibility.good("batches").empty(), "Environment mismatch admitted part of a batch");
        target["execution_environment"]["architecture"] = "aarch64";
        target["execution_environment"]["os"] = "darwin";
        report("alpha");
        checked = compatibility.good("preflight", portable);
        require(!checked.at("valid").get<bool>() && checked.at("errors")[0].at("reasons").dump().find("OS mismatch") != std::string::npos,
                "Operating system mismatch accepted");
        target["execution_environment"]["os"] = "linux";
        target["execution_environment"]["commands"] = Json::array();
        report("alpha");
        checked = compatibility.good("preflight", portable);
        require(!checked.at("valid").get<bool>() && checked.at("errors")[0].at("reasons").dump().find("command missing") != std::string::npos,
                "Missing command accepted");
        target["execution_environment"]["commands_complete"] = false;
        report("alpha");
        checked = compatibility.good("preflight", portable);
        require(!checked.at("valid").get<bool>() && checked.at("errors")[0].at("reasons").dump().find("incomplete inventory") != std::string::npos,
                "Incomplete inventory presented as a complete command list");
        portable["artifact_requirements"] = Json::object();
        require(compatibility.good("preflight", portable).at("valid").get<bool>(), "Legacy bundle acquired environment requirements");

        Fixture lifecycle;
        enroll(lifecycle);
        require(lifecycle.good("workspace_mode").at("demo").get<bool>(), "Legacy Store demo default changed");
        auto demo_batch = lifecycle.good("submit", submission("demo-off"));
        auto demo_run = lifecycle.good("poll", {{"board_id", "alpha"}});
        lifecycle.good("set_workspace_mode", {{"enabled", false}});
        require(!lifecycle.good("workspace_mode").at("demo").get<bool>(), "Demo setting not saved");
        require(lifecycle.good("poll", {{"board_id", "alpha"}}).at("state") == "cancelling", "Disabled demo lost cancellation acknowledgement path");
        require(lifecycle.good("poll", {{"board_id", "beta"}}).is_null(), "Disabled demo claimed queued work");
        require(!lifecycle.good("preflight", submission("demo-blocked")).at("valid").get<bool>(), "Hidden synthetic ID bypassed demo admission");
        lifecycle.good("finish", {{"board_id", "alpha"}, {"run_id", demo_run.at("id")}, {"completion", completion()}});
        require(lifecycle.good("batch", {{"batch_id", demo_batch.at("id")}}).at("runs")[1].at("state") == "cancelled", "Queued synthetic work survived demo disable");
        lifecycle.good("set_workspace_mode", {{"enabled", true}});
        lifecycle.good("board_action", {{"board_id", "alpha"}, {"action", "reload"}});
        auto single = submission("reload-blocked", plan({"alpha"}));
        require(!lifecycle.good("preflight", single).at("valid").get<bool>(), "Reload request failed to gate admission");
        lifecycle.good("heartbeat", {{"board_id", "alpha"}, {"heartbeat", {{"description", description()}, {"reload_ack", 1}, {"reload_error", "invalid module"}}}});
        require(!lifecycle.good("preflight", single).at("valid").get<bool>(), "Failed reload acknowledgement released admission");
        lifecycle.good("heartbeat", {{"board_id", "alpha"}, {"heartbeat", {{"description", description('d')}, {"reload_ack", 1}, {"reload_error", nullptr}}}});
        require(lifecycle.good("preflight", single).at("valid").get<bool>(), "Successful reload stayed blocked");
        auto force_batch = lifecycle.good("submit", single);
        auto force_run = lifecycle.good("poll", {{"board_id", "alpha"}});
        lifecycle.good("board_action", {{"board_id", "alpha"}, {"action", "force-reload"}});
        require(lifecycle.good("poll", {{"board_id", "alpha"}}).at("state") == "cancelling", "Forced reload did not cancel current execution");
        lifecycle.good("finish", {{"board_id", "alpha"}, {"run_id", force_run.at("id")}, {"completion", completion(false, 'd')}});
        lifecycle.good("heartbeat", {{"board_id", "alpha"}, {"heartbeat", {{"description", description()}, {"reload_ack", 2}}}});
        require(lifecycle.good("boards")[0].at("quarantined") == 1, "Reload acknowledgement cleared uncertain cleanup");

        Fixture restart;
        enroll(restart);
        auto real = description();
        real["mode"] = "linux-process";
        restart.good("heartbeat", {{"board_id", "alpha"}, {"heartbeat", {{"description", real}}}});
        restart.good("submit", submission("before-restart", plan({"alpha"})));
        auto old_run = restart.good("poll", {{"board_id", "alpha"}});
        auto begin = restart.good("board_action", {{"board_id", "alpha"}, {"action", "restart"}, {"restart_id", "restart-1"}});
        require(restart.good("board_action", {{"board_id", "alpha"}, {"action", "restart"}, {"restart_id", "retry"}}).at("restart_id") == begin.at("restart_id"), "Restart retry replaced maintenance identity");
        require(restart.good("poll", {{"board_id", "alpha"}}).at("state") == "cancelling", "Maintenance hid active cancellation");
        restart.bad("board_action", {{"board_id", "alpha"}, {"action", "recover"}}, "conflict");
        Json reboot = {{"board_id", "alpha"}, {"action", "restart-complete"}, {"restart_id", "restart-1"},
                       {"instance_id", "lab-instance"}, {"boot_id_before", "old-boot"}, {"boot_id_after", "new-boot"}, {"agent_ready", true}};
        auto invalid_reboot = reboot;
        invalid_reboot["restart_id"] = "stale";
        restart.bad("board_action", invalid_reboot, "conflict");
        invalid_reboot = reboot;
        invalid_reboot["boot_id_after"] = "old-boot";
        restart.bad("board_action", invalid_reboot, "conflict");
        restart.good("board_action", reboot);
        auto interrupted = restart.good("batch", {{"batch_id", old_run.at("batch_id")}}).at("runs")[0];
        require(interrupted.at("state") == "cancelled" && interrupted.at("result").at("restart_cleanup").at("cleanup_ok").get<bool>(), "Reboot did not retain interrupted execution evidence");
        require(restart.good("boards")[0].at("status") == "ready", "Verified reboot did not release its own maintenance gate");
        restart.sql("UPDATE boards SET quarantined=1 WHERE id='alpha'");
        restart.good("board_action", {{"board_id", "alpha"}, {"action", "restart"}, {"restart_id", "restart-2"}});
        reboot["restart_id"] = "restart-2";
        restart.good("board_action", reboot);
        require(restart.good("boards")[0].at("quarantined") == 1, "Reboot cleared unrelated preexisting quarantine");

        Fixture queue;
        enroll(queue);
        queue.good("submit", submission("queue-active", plan({"alpha"})));
        auto waiting = submission("queue-first");
        waiting["enqueue"] = true;
        auto waiting_batch = queue.good("submit", waiting);
        require(waiting_batch.at("queue_position") == 1 && waiting_batch.at("runs")[0].at("state") == "waiting",
                "Busy batch did not wait without a lease");
        require(waiting_batch.at("runs")[0].at("module_sha256").is_null(), "Waiting work pinned an early generation");
        require(queue.good("poll", {{"board_id", "beta"}}).is_null(), "Waiting batch reserved only part of its targets");
        auto retry_without_queue = waiting;
        retry_without_queue["enqueue"] = false;
        queue.bad("submit", retry_without_queue, "conflict");
        queue.bad("submit", submission("queue-jump", plan({"beta"})), "conflict");
        heartbeat(queue, "beta", 'd');
        auto queue_active = queue.good("poll", {{"board_id", "alpha"}});
        queue.good("finish", {{"board_id", "alpha"}, {"run_id", queue_active.at("id")}, {"completion", completion()}});
        auto released = queue.good("batch", {{"batch_id", waiting_batch.at("id")}});
        require(released.at("queue_position").is_null(), "Admitted batch retained a queue position");
        require(released.at("runs")[0].at("state") == "queued" && released.at("runs")[1].at("state") == "queued",
                "Waiting batch admission was not atomic");
        require(queue.good("poll", {{"board_id", "beta"}}).at("module_sha256") == std::string(64, 'd'),
                "Queue dispatch did not pin the latest generation");

        Fixture legacy;
        legacy.sql("CREATE TABLE boards (id TEXT PRIMARY KEY,name TEXT NOT NULL,board_profile TEXT NOT NULL,"
                   "system_profile TEXT NOT NULL,token_hash TEXT NOT NULL,description TEXT,seen REAL NOT NULL DEFAULT 0,"
                   "quarantined INTEGER NOT NULL DEFAULT 0,reload_requested INTEGER NOT NULL DEFAULT 0,"
                   "reload_ack INTEGER NOT NULL DEFAULT 0,reload_error TEXT,local INTEGER NOT NULL DEFAULT 0);"
                   "INSERT INTO boards(id,name,board_profile,system_profile,token_hash) VALUES('legacy','preserved','generic','linux-process','legacy-token');");
        legacy.good("init");
        legacy.good("init");
        const auto migrated = legacy.good("boards");
        require(migrated.size() == 1 && migrated[0].at("name") == "preserved" && migrated[0].at("maintenance").is_null(), "Additive schema migration lost an old board");
        std::cout << "Native SQLite transaction, concurrency, lifecycle and ABI checks passed\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
