#include "side_galaxy_core.h"
#include <nlohmann/json.hpp>
#include <sqlite3.h>

#include <algorithm>
#include <chrono>
#include <cstdlib>
#include <cstring>
#include <initializer_list>
#include <limits>
#include <map>
#include <set>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace {
using Json = nlohmann::json;

struct Error : std::runtime_error {
    std::string kind;
    Error(std::string type, std::string message) : std::runtime_error(std::move(message)), kind(std::move(type)) {}
};

[[noreturn]] void invalid(const char* message) { throw Error("invalid", message); }
[[noreturn]] void missing() { throw Error("not_found", "Not found"); }
[[noreturn]] void conflict(const std::string& message) { throw Error("conflict", message); }

double now() {
    return std::chrono::duration<double>(std::chrono::system_clock::now().time_since_epoch()).count();
}

void sql_check(int code) {
    if (code == SQLITE_OK || code == SQLITE_DONE || code == SQLITE_ROW) return;
    if ((code & 0xff) == SQLITE_CONSTRAINT) conflict("Database constraint rejected the operation");
    if (code == SQLITE_BUSY || code == SQLITE_LOCKED) conflict("Database is busy; retry the same operation");
    throw Error("internal", "SQLite operation failed (" + std::to_string(code) + ")");
}

class Database {
    sqlite3* db_ = nullptr;
    bool transaction_ = false;
    // Statements are reused only within one call/connection; no shared connection or cache state.
    std::map<std::string, sqlite3_stmt*, std::less<>> statements_;
public:
    explicit Database(const char* path) {
        int code = sqlite3_open_v2(path, &db_, SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE | SQLITE_OPEN_FULLMUTEX, nullptr);
        if (code != SQLITE_OK) {
            if (db_) sqlite3_close(db_);
            db_ = nullptr;
            sql_check(code);
        }
        sqlite3_busy_timeout(db_, 10000);
        try {
            // Pin durability across system SQLite builds instead of inheriting platform WAL defaults.
            sql_check(sqlite3_exec(db_, "PRAGMA foreign_keys=ON;PRAGMA synchronous=FULL;PRAGMA checkpoint_fullfsync=ON",
                                   nullptr, nullptr, nullptr));
        }
        catch (...) { sqlite3_close(db_); db_ = nullptr; throw; }
    }
    Database(const Database&) = delete;
    Database& operator=(const Database&) = delete;
    ~Database() {
        if (transaction_) sqlite3_exec(db_, "ROLLBACK", nullptr, nullptr, nullptr);
        for (const auto& [sql, statement] : statements_) sqlite3_finalize(statement);
        if (db_) sqlite3_close(db_);
    }
    std::vector<Json> query(const char* sql, std::initializer_list<Json> values = {}) {
        sqlite3_stmt* raw = nullptr;
        if (const auto cached = statements_.find(sql); cached != statements_.end()) raw = cached->second;
        else {
            sql_check(sqlite3_prepare_v2(db_, sql, -1, &raw, nullptr));
            try { statements_.emplace(sql, raw); }
            catch (...) { sqlite3_finalize(raw); throw; }
        }
        struct Reset {
            sqlite3_stmt* value;
            ~Reset() { sqlite3_reset(value); sqlite3_clear_bindings(value); }
        } reset{raw};
        int index = 1;
        for (const auto& value : values) {
            int code;
            if (value.is_null()) code = sqlite3_bind_null(raw, index);
            else if (value.is_boolean()) code = sqlite3_bind_int(raw, index, value.get<bool>() ? 1 : 0);
            else if (value.is_number_integer()) code = sqlite3_bind_int64(raw, index, value.get<sqlite3_int64>());
            else if (value.is_number_float()) code = sqlite3_bind_double(raw, index, value.get<double>());
            else if (value.is_string()) {
                const auto& text = value.get_ref<const std::string&>();
                if (text.size() > static_cast<std::size_t>(std::numeric_limits<int>::max())) invalid("SQL value is too large");
                code = sqlite3_bind_text(raw, index, text.data(), static_cast<int>(text.size()), SQLITE_TRANSIENT);
            } else invalid("SQL parameters must be scalar values");
            sql_check(code);
            ++index;
        }
        std::vector<Json> rows;
        int code;
        const int columns = sqlite3_column_count(raw);
        while ((code = sqlite3_step(raw)) == SQLITE_ROW) {
            Json row = Json::object();
            for (int column = 0; column < columns; ++column) {
                const char* key = sqlite3_column_name(raw, column);
                switch (sqlite3_column_type(raw, column)) {
                case SQLITE_NULL: row[key] = nullptr; break;
                case SQLITE_INTEGER: row[key] = sqlite3_column_int64(raw, column); break;
                case SQLITE_FLOAT: row[key] = sqlite3_column_double(raw, column); break;
                case SQLITE_TEXT: {
                    const auto* bytes = reinterpret_cast<const char*>(sqlite3_column_text(raw, column));
                    row[key] = std::string(bytes, static_cast<std::size_t>(sqlite3_column_bytes(raw, column)));
                    break;
                }
                default: throw Error("internal", "Unexpected database column type");
                }
            }
            rows.push_back(std::move(row));
        }
        sql_check(code);
        return rows;
    }
    void execute(const char* sql, std::initializer_list<Json> values = {}) { (void)query(sql, values); }
    Json one(const char* sql, std::initializer_list<Json> values = {}) {
        auto rows = query(sql, values);
        return rows.empty() ? Json(nullptr) : std::move(rows.front());
    }
    void begin() { execute("BEGIN IMMEDIATE"); transaction_ = true; }
    void commit() { execute("COMMIT"); transaction_ = false; }
};

void schema(Database& db) {
    db.execute("CREATE TABLE IF NOT EXISTS boards ("
               "id TEXT PRIMARY KEY,name TEXT NOT NULL,board_profile TEXT NOT NULL,"
               "system_profile TEXT NOT NULL,token_hash TEXT NOT NULL,description TEXT,"
               "seen REAL NOT NULL DEFAULT 0,quarantined INTEGER NOT NULL DEFAULT 0,"
               "reload_requested INTEGER NOT NULL DEFAULT 0,reload_ack INTEGER NOT NULL DEFAULT 0,"
               "reload_error TEXT,local INTEGER NOT NULL DEFAULT 0)");
    bool maintenance_column = false, physical_host_column = false;
    for (const auto& column : db.query("PRAGMA table_info(boards)")) {
        maintenance_column |= column.at("name") == "maintenance";
        physical_host_column |= column.at("name") == "physical_host_id";
    }
    if (!maintenance_column) db.execute("ALTER TABLE boards ADD COLUMN maintenance TEXT");
    if (!physical_host_column) db.execute("ALTER TABLE boards ADD COLUMN physical_host_id TEXT");
    db.execute("CREATE INDEX IF NOT EXISTS board_physical_host ON boards(physical_host_id)");
    db.execute("CREATE TABLE IF NOT EXISTS workspace_settings (id INTEGER PRIMARY KEY CHECK(id=1),demo INTEGER NOT NULL)");
    db.execute("CREATE TABLE IF NOT EXISTS batches (id TEXT PRIMARY KEY,key TEXT UNIQUE NOT NULL,"
               "plan TEXT NOT NULL,sha256 TEXT NOT NULL,created REAL NOT NULL)");
    std::set<std::string> batch_columns;
    for (const auto& column : db.query("PRAGMA table_info(batches)")) batch_columns.insert(column.at("name"));
    if (!batch_columns.contains("enqueue")) db.execute("ALTER TABLE batches ADD COLUMN enqueue INTEGER NOT NULL DEFAULT 0");
    if (!batch_columns.contains("admission_contract")) db.execute("ALTER TABLE batches ADD COLUMN admission_contract TEXT");
    if (!batch_columns.contains("waiting_reason")) db.execute("ALTER TABLE batches ADD COLUMN waiting_reason TEXT");
    db.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY,"
               "batch_id TEXT NOT NULL REFERENCES batches(id),board_id TEXT NOT NULL REFERENCES boards(id),"
               "state TEXT NOT NULL,created REAL NOT NULL,started REAL,finished REAL,module_sha256 TEXT,result TEXT)");
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS board_lease ON runs(board_id) "
               "WHERE state IN ('queued','running','cancelling')");
    bool run_host_column = false;
    for (const auto& column : db.query("PRAGMA table_info(runs)")) run_host_column |= column.at("name") == "physical_host_key";
    if (!run_host_column) db.execute("ALTER TABLE runs ADD COLUMN physical_host_key TEXT");
    db.execute("UPDATE runs SET physical_host_key=(SELECT COALESCE('host:'||b.physical_host_id,'board:'||b.id) "
               "FROM boards b WHERE b.id=runs.board_id) WHERE physical_host_key IS NULL AND state!='waiting' AND module_sha256 IS NOT NULL");
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS physical_host_lease ON runs(physical_host_key) "
               "WHERE state IN ('queued','running','cancelling')");
}

std::string string_field(const Json& object, const char* name, std::size_t maximum = 256) {
    const auto& value = object.at(name);
    if (!value.is_string()) invalid("Expected a string field");
    const auto& text = value.get_ref<const std::string&>();
    if (text.empty() || text.size() > maximum || text.find('\0') != std::string::npos) invalid("Invalid string field");
    return text;
}

bool hash_string(const std::string& value) {
    return value.size() == 64 && std::all_of(value.begin(), value.end(), [](unsigned char c) {
        return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f');
    });
}

std::string hash_field(const Json& value, const char* name) {
    auto text = string_field(value, name, 64);
    if (!hash_string(text)) invalid("Expected a lowercase SHA-256 digest");
    return text;
}

bool constant_time_hash_equal(const std::string& left, const std::string& right) {
    if (left.size() != 64 || right.size() != 64) return false;
    unsigned difference = 0;
    for (std::size_t i = 0; i < 64; ++i)
        difference |= static_cast<unsigned char>(left[i]) ^ static_cast<unsigned char>(right[i]);
    return difference == 0;
}

bool contains(const Json& values, const Json& wanted) {
    return values.is_array() && std::find(values.begin(), values.end(), wanted) != values.end();
}

Json parsed(const Json& value, Json fallback = nullptr) {
    return value.is_null() ? std::move(fallback) : Json::parse(value.get_ref<const std::string&>());
}

// Classification also covers old boards whose module description has not arrived yet.
bool synthetic_board(const Json& board) {
    return board.value("local", 0) != 0 || board.value("system_profile", std::string()) == "simulator"
        || parsed(board.value("description", Json(nullptr)), Json::object()).value("mode", std::string()) == "synthetic";
}

bool demo_enabled(Database& db) {
    const auto setting = db.one("SELECT demo FROM workspace_settings WHERE id=1");
    // Direct Store users retain compatibility; the HTTP server explicitly chooses its startup policy.
    return setting.is_null() || setting.at("demo").get<int>() != 0;
}

bool reload_pending(const Json& board) {
    return board.at("reload_requested").get<int>() > board.at("reload_ack").get<int>()
        || (board.at("reload_requested").get<int>() > 0 && !board.at("reload_error").is_null());
}

std::string physical_host_key(const Json& board) {
    return board.at("physical_host_id").is_null() ? "board:" + board.at("id").get<std::string>()
        : "host:" + board.at("physical_host_id").get<std::string>();
}

std::vector<Json> host_members(Database& db, const Json& board) {
    return db.query("SELECT id,quarantined,maintenance,reload_requested,reload_ack,reload_error FROM boards "
                    "WHERE physical_host_id=? OR id=?", {board.at("physical_host_id"), board.at("id")});
}

Json host_state(Database& db, const Json& board) {
    Json state = {{"physical_host_key", physical_host_key(board)},
                  {"physical_host_identity_known", !board.at("physical_host_id").is_null()},
                  {"host_quarantined", false}, {"host_maintenance", false}, {"host_reload_pending", false},
                  {"host_quarantine_sources", Json::array()}, {"host_active_run", nullptr}, {"host_active_board_id", nullptr}};
    for (const auto& member : host_members(db, board)) {
        if (member.at("quarantined").get<int>()) {
            state["host_quarantined"] = true;
            state["host_quarantine_sources"].push_back(member.at("id"));
        }
        if (!member.at("maintenance").is_null()) state["host_maintenance"] = true;
        if (reload_pending(member)) state["host_reload_pending"] = true;
    }
    const auto active = db.one("SELECT id,board_id FROM runs WHERE physical_host_key=? "
                               "AND state IN ('queued','running','cancelling')", {state.at("physical_host_key")});
    if (!active.is_null()) {
        state["host_active_run"] = active.at("id");
        state["host_active_board_id"] = active.at("board_id");
    }
    return state;
}

void cancel_board(Database& db, const Json& board_id, const char* reason) {
    db.execute("UPDATE runs SET state='cancelled',finished=?,result=? WHERE board_id=? AND state='queued'",
               {now(), Json{{"error", reason}, {"code_executed", false}, {"cleanup_ok", true}}.dump(), board_id});
    db.execute("UPDATE runs SET state='cancelling' WHERE board_id=? AND state='running'", {board_id});
}

void validate_plan(const Json& plan) {
    if (!plan.is_object() || plan.dump(-1, ' ', true).size() > 32768) invalid("Invalid or oversized plan");
    const auto& boards = plan.at("boards");
    const auto& cpus = plan.at("cpus");
    const auto& interference = plan.at("interference_cpus");
    if (!boards.is_array() || boards.empty() || boards.size() > 32) invalid("Invalid plan board list");
    if (!cpus.is_array() || cpus.empty() || cpus.size() > 64 || !interference.is_array() || interference.size() > 64)
        invalid("Invalid plan CPU lists");
    std::set<std::string> unique_boards;
    for (const auto& board : boards) {
        if (!board.is_string() || board.get_ref<const std::string&>().empty()
            || !unique_boards.insert(board.get<std::string>()).second) invalid("Invalid or duplicate board ID");
    }
    std::set<std::int64_t> unique_cores;
    for (const auto* cores : {&cpus, &interference}) {
        for (const auto& core : *cores) {
            if (!core.is_number_integer() || core.get<std::int64_t>() < 0
                || !unique_cores.insert(core.get<std::int64_t>()).second) invalid("CPU lists must be nonnegative, unique and disjoint");
        }
    }
    const auto policy = plan.value("resource_policy", std::string("auto"));
    if (policy != "auto" && policy != "cgroup") invalid("Invalid resource policy");
    const auto mode = string_field(plan, "template", 64);
    if (!plan.value("environment_sha256", Json(nullptr)).is_null()) {
        hash_field(plan, "environment_sha256");
        if (mode != "workload") invalid("Environment bundles require workload template");
    }
    if (!plan.at("duration_seconds").is_number_integer()) invalid("Invalid experiment duration");
    auto duration = plan.at("duration_seconds").get<std::int64_t>();
    if (duration < 1 || duration > (mode == "workload" ? 86400 : 120)) invalid("Invalid experiment duration");
    if (mode == "workload") {
        hash_field(plan, "artifact_sha256");
        if (!interference.empty()) invalid("Workload must leave interference CPUs empty");
    } else if (!plan.value("artifact_sha256", Json(nullptr)).is_null()
               || !plan.value("arguments", Json::array()).empty() || !plan.value("environment", Json::object()).empty()) {
        invalid("Artifact, arguments and environment require workload template");
    }
    for (const auto& pair : {std::pair{"memory_mib", 65536}, std::pair{"bandwidth_percent", 100}}) {
        const auto value = plan.value(pair.first, Json(nullptr));
        if (!value.is_null() && (!value.is_number_integer() || value.get<std::int64_t>() < (std::string_view(pair.first) == "memory_mib" ? 128 : 1)
            || value.get<std::int64_t>() > pair.second)) invalid("Invalid resource limit");
    }
}

void expire(Database& db) {
    const double timestamp = now();
    for (const auto& row : db.query("SELECT r.id,r.board_id,r.state,r.started,b.seen,ba.plan FROM runs r JOIN boards b ON b.id=r.board_id "
                                    "JOIN batches ba ON ba.id=r.batch_id WHERE r.state IN ('queued','running','cancelling')")) {
        const auto plan = parsed(row.at("plan"));
        const double duration = plan.at("duration_seconds").get<double>();
        // Environment staging can download for 900 s before the execution clock
        // begins. Allow validation/unpack, 240 s execution overhead and cleanup;
        // the independent 30 s heartbeat gate still detects disconnected agents.
        const double grace = !plan.value("environment_sha256", Json(nullptr)).is_null() ? 1800
            : plan.at("template") == "workload" ? 180 : 45;
        if (timestamp - row.at("seen").get<double>() > 30
            || (!row.at("started").is_null() && timestamp - row.at("started").get<double>() > duration + grace)) {
            db.execute("UPDATE runs SET state=?,finished=?,result=? WHERE id=?",
                       {row.at("state") == "queued" ? "failed" : "lost", timestamp,
                        Json{{"error", "agent heartbeat or execution deadline expired"}}.dump(), row.at("id")});
            db.execute("UPDATE boards SET quarantined=1 WHERE id=?", {row.at("board_id")});
        }
    }
}

Json run_view(Json row) {
    row["queue_position"] = nullptr;
    row["waiting_reason"] = nullptr;
    row["result"] = parsed(row.at("result"));
    auto& result = row["result"];
    if (row.at("state") == "lost" && result.is_object() && result.contains("late_completion")
        && result["late_completion"].is_object()) {
        auto& late_result = result["late_completion"]["result"];
        if (late_result.is_object() && late_result.contains("outputs") && late_result["outputs"].is_array())
            for (auto& item : late_result["outputs"]) if (item.is_object()) item.erase("data_base64");
    }
    if (result.is_object() && result.contains("outputs") && result["outputs"].is_array()) {
        Json outputs = Json::array();
        for (auto item : result["outputs"]) {
            if (item.is_object()) {
                item.erase("data_base64");
                outputs.push_back(std::move(item));
            }
        }
        result["outputs"] = std::move(outputs);
    }
    return row;
}

Json batch_view(Database& db, const Json& batch_id) {
    auto result = db.one("SELECT * FROM batches WHERE id=?", {batch_id});
    if (result.is_null()) missing();
    result.erase("key");
    result.erase("admission_contract");
    const auto waiting = db.one("SELECT 1 FROM runs WHERE batch_id=? AND state='waiting'", {batch_id});
    result["queue_position"] = waiting.is_null() ? Json(nullptr) : db.one(
        "SELECT COUNT(*) AS position FROM batches b WHERE b.rowid <= (SELECT rowid FROM batches WHERE id=?) "
        "AND EXISTS(SELECT 1 FROM runs r WHERE r.batch_id=b.id AND r.state='waiting')", {batch_id}).at("position");
    if (waiting.is_null()) result["waiting_reason"] = nullptr;
    result["plan"] = parsed(result.at("plan"));
    result["runs"] = Json::array();
    for (auto& row : db.query("SELECT * FROM runs WHERE batch_id=? ORDER BY created,id", {batch_id})) {
        auto run = run_view(std::move(row));
        if (run.at("state") == "waiting") {
            run["queue_position"] = result.at("queue_position");
            run["waiting_reason"] = result.at("waiting_reason");
        }
        result["runs"].push_back(std::move(run));
    }
    return result;
}

void check_environment(Json& reasons, const Json& requirements, const Json& description) {
    if (!requirements.is_object()) invalid("Artifact requirements must be an object");
    const auto architectures = requirements.value("architectures", Json::array());
    const auto commands = requirements.value("commands", Json::array());
    if (!architectures.is_array() || !commands.is_array()) invalid("Invalid artifact environment requirements");
    if (architectures.empty() && commands.empty() && !requirements.contains("os")) return;
    const auto environment = description.value("execution_environment", Json(nullptr));
    if (!environment.is_object()) {
        reasons.push_back("execution environment unknown; update or reload the target module");
        return;
    }
    const auto architecture = environment.value("architecture", std::string("unknown"));
    if (!architectures.empty() && !contains(architectures, architecture))
        reasons.push_back("execution architecture mismatch: requires " + architectures.dump() + "; target " + architecture);
    const auto operating_system = environment.value("os", std::string("unknown"));
    if (requirements.contains("os") && requirements.at("os") != operating_system)
        reasons.push_back("execution OS mismatch: requires " + requirements.at("os").get<std::string>() + "; target " + operating_system);
    const auto available = environment.value("commands", Json::array());
    for (const auto& command : commands) {
        if (!contains(available, command)) {
            const char* message = environment.value("commands_complete", false)
                ? "required execution command missing: " : "required command not confirmed (incomplete inventory): ";
            reasons.push_back(std::string(message) + command.get<std::string>());
        }
    }
}

Json check_plan(Database& db, const Json& payload, bool allow_wait = false) {
    const auto& plan = payload.at("plan");
    const auto plan_hash = hash_field(payload, "plan_sha256");
    validate_plan(plan);
    Json errors = Json::array(), targets = Json::array();
    if (!plan.value("artifact_sha256", Json(nullptr)).is_null() && !payload.value("artifact_available", false))
        errors.push_back({{"board_id", nullptr}, {"reasons", Json::array({"artifact unavailable; upload again"})}});
    const bool environment_bundle = !plan.value("environment_sha256", Json(nullptr)).is_null();
    if (environment_bundle && !payload.value("environment_available", false))
        errors.push_back({{"board_id", nullptr}, {"reasons", Json::array({"environment unavailable; upload again"})}});
    const double timestamp = now();
    const bool demo = demo_enabled(db);
    Json cores = plan.at("cpus");
    for (const auto& core : plan.at("interference_cpus")) cores.push_back(core);
    std::set<std::string> physical_hosts;
    for (const auto& board_id : plan.at("boards")) {
        const auto board = db.one("SELECT * FROM boards WHERE id=?", {board_id});
        Json reasons = Json::array();
        if (board.is_null()) {
            errors.push_back({{"board_id", board_id}, {"reasons", Json::array({"unknown board"})}});
            continue;
        }
        const auto host = host_state(db, board);
        if (!physical_hosts.insert(host.at("physical_host_key").get<std::string>()).second)
            reasons.push_back("batch selects multiple targets on the same physical host");
        const auto description = parsed(board.at("description"), Json::object());
        if (!demo && synthetic_board(board)) reasons.push_back("demo mode disabled; synthetic admission is blocked");
        if (!allow_wait) {
            if (host.at("host_maintenance").get<bool>()) reasons.push_back("physical host restart maintenance is pending");
            if (host.at("host_reload_pending").get<bool>()) reasons.push_back("physical host module reload pending or failed; await a successful acknowledgement");
            if (timestamp - board.at("seen").get<double>() > 30) reasons.push_back("board offline");
            if (host.at("host_quarantined").get<bool>()) reasons.push_back("physical host quarantined; verify cleanup before recovery");
            if (!host.at("host_active_run").is_null()) reasons.push_back("physical host lease occupied");
        }
        // An enrolled, never-connected target has no capabilities to validate yet.
        // It may wait, but admission always requires its first validated description.
        if (allow_wait && description.empty()) {
            if (!reasons.empty()) errors.push_back({{"board_id", board_id}, {"reasons", std::move(reasons)}});
            targets.push_back({{"board_id", board_id}, {"name", board.at("name")}, {"mode", nullptr}, {"module_sha256", nullptr}, {"physical_host_key", host.at("physical_host_key")}});
            continue;
        }
        bool unavailable = false, reserved = false;
        const auto available_cores = description.value("cpus", Json::array());
        const auto reserved_cores = description.value("reserved_cpus", Json::array());
        for (const auto& core : cores) {
            unavailable |= !contains(available_cores, core);
            reserved |= contains(reserved_cores, core);
        }
        if (unavailable) reasons.push_back("CPU unavailable");
        if (reserved) reasons.push_back("management CPU reserved");
        if (!contains(description.value("templates", Json::array()), plan.at("template"))) reasons.push_back("template unsupported");
        const auto caps = description.value("capabilities", Json::array());
        if (description.value("environment_required", false) && !environment_bundle)
            reasons.push_back("module requires an environment bundle");
        if (environment_bundle) {
            if (!contains(caps, "environment-bundle")) reasons.push_back("module does not support environment bundles");
            if (!contains(description.value("environment_architectures", Json::array()), payload.value("environment_architecture", Json(nullptr))))
                reasons.push_back("environment architecture unsupported by target");
        }
        if (plan.value("resource_policy", std::string("auto")) == "cgroup" && !contains(caps, "process-tree-limits"))
            reasons.push_back("process-tree resource limits unsupported");
        if (!contains(caps, "cpu-affinity")) reasons.push_back("CPU affinity unsupported");
        const auto memory = plan.value("memory_mib", Json(nullptr));
        if (memory.is_null() && plan.value("resource_policy", std::string("auto")) == "cgroup")
            reasons.push_back("process-tree resource limits require a memory budget");
        if (memory.is_null() && description.value("memory_limit_required", false)) reasons.push_back("module requires a memory limit");
        if (!memory.is_null() && (!contains(caps, "memory-limit") || memory.get<double>() > description.value("memory_mib", 0.0)))
            reasons.push_back("memory limit unsupported or exceeds available budget");
        if (environment_bundle && !memory.is_null()
            && memory.get<double>() + description.value("memory_overhead_mib", 0.0) > description.value("memory_mib", 0.0))
            reasons.push_back("guest memory plus host overhead exceeds available budget");
        if (!plan.value("bandwidth_percent", Json(nullptr)).is_null() && !contains(caps, "bandwidth-limit"))
            reasons.push_back("hardware bandwidth control unsupported");
        if (!plan.at("interference_cpus").empty() && !contains(caps, "interference")) reasons.push_back("module does not support interferers");
        if (plan.at("template") == "workload") {
            auto execution_description = description;
            if (environment_bundle) execution_description["execution_environment"] = payload.value("environment_runtime", Json(nullptr));
            check_environment(reasons, payload.value("artifact_requirements", Json::object()), execution_description);
        }
        if (!reasons.empty()) errors.push_back({{"board_id", board_id}, {"reasons", std::move(reasons)}});
        targets.push_back({{"board_id", board_id}, {"name", board.at("name")}, {"mode", description.value("mode", Json(nullptr))},
                           {"module_sha256", description.value("module_sha256", Json(nullptr))}, {"physical_host_key", host.at("physical_host_key")}});
    }
    return {{"valid", errors.empty()}, {"errors", std::move(errors)}, {"targets", std::move(targets)}, {"plan_sha256", plan_hash}};
}

std::string waiting_reason(const Json& checked) {
    std::set<std::string> seen;
    std::string message;
    for (const auto& error : checked.at("errors"))
        for (const auto& reason : error.at("reasons")) {
            const auto text = reason.get<std::string>();
            if (seen.insert(text).second) {
                if (!message.empty()) message += "; ";
                message += text;
            }
        }
    return message;
}

bool waiting_overlap(Database& db, const Json& plan) {
    std::set<std::string> hosts;
    for (const auto& id : plan.at("boards")) {
        const auto board = db.one("SELECT id,physical_host_id FROM boards WHERE id=?", {id});
        if (!board.is_null()) hosts.insert(physical_host_key(board));
    }
    for (const auto& board : db.query("SELECT DISTINCT b.id,b.physical_host_id FROM runs r JOIN boards b ON b.id=r.board_id WHERE r.state='waiting'"))
        if (hosts.contains(physical_host_key(board))) return true;
    return false;
}

void dispatch_waiting(Database& db) {
    // ponytail: one bounded FIFO pass per transaction; no scheduler thread or second queue database.
    std::set<std::string> blocked;
    for (const auto& batch : db.query("SELECT b.id,b.admission_contract FROM batches b "
                                     "WHERE EXISTS(SELECT 1 FROM runs r WHERE r.batch_id=b.id AND r.state='waiting') ORDER BY b.rowid")) {
        const auto contract = parsed(batch.at("admission_contract"));
        const auto compatible = check_plan(db, contract, true);
        if (!compatible.at("valid").get<bool>()) {
            db.execute("UPDATE runs SET state='failed',finished=?,result=? WHERE batch_id=? AND state='waiting'",
                       {now(), Json{{"error", waiting_reason(compatible)}, {"code_executed", false}, {"cleanup_ok", true}}.dump(), batch.at("id")});
            db.execute("UPDATE batches SET waiting_reason=NULL WHERE id=?", {batch.at("id")});
            continue;
        }
        bool earlier = false;
        for (const auto& target : compatible.at("targets")) earlier |= blocked.contains(target.at("physical_host_key").get<std::string>());
        const auto checked = check_plan(db, contract);
        if (earlier || !checked.at("valid").get<bool>()) {
            for (const auto& target : compatible.at("targets")) blocked.insert(target.at("physical_host_key").get<std::string>());
            db.execute("UPDATE batches SET waiting_reason=? WHERE id=?",
                       {earlier ? "Earlier waiting batch shares a physical host" : waiting_reason(checked), batch.at("id")});
            continue;
        }
        for (const auto& target : checked.at("targets"))
            db.execute("UPDATE runs SET state='queued',module_sha256=?,physical_host_key=? WHERE batch_id=? AND board_id=? AND state='waiting'",
                       {target.at("module_sha256"), target.at("physical_host_key"), batch.at("id"), target.at("board_id")});
        db.execute("UPDATE batches SET waiting_reason=NULL WHERE id=?", {batch.at("id")});
    }
}

Json dispatch(Database& db, const std::string& operation, const Json& payload) {
    if (operation == "init") {
        schema(db);
        return {{"initialized", true}};
    }
    if (operation == "workspace_mode") return {{"demo", demo_enabled(db)}};
    if (operation == "set_workspace_mode") {
        const bool enabled = payload.at("enabled").get<bool>();
        db.execute("INSERT INTO workspace_settings(id,demo) VALUES(1,?) ON CONFLICT(id) DO UPDATE SET demo=excluded.demo", {enabled});
        if (!enabled)
            for (const auto& board : db.query("SELECT local,system_profile,description,id FROM boards"))
                if (synthetic_board(board)) cancel_board(db, board.at("id"), "Demo mode disabled");
        return {{"demo", enabled}};
    }
    if (operation == "enroll") {
        const auto id = string_field(payload, "board_id");
        const auto& data = payload.at("data");
        db.execute("INSERT INTO boards(id,name,board_profile,system_profile,token_hash,local) VALUES(?,?,?,?,?,?)",
                   {id, string_field(data, "name"), string_field(data, "board_profile", 64), string_field(data, "system_profile", 64),
                    hash_field(payload, "token_hash"), payload.value("local", false)});
        return {{"board_id", id}};
    }
    if (operation == "agent_allowed") {
        const auto row = db.one("SELECT token_hash FROM boards WHERE id=?", {string_field(payload, "board_id")});
        return !row.is_null() && constant_time_hash_equal(row.at("token_hash").get<std::string>(), hash_field(payload, "token_hash"));
    }
    if (operation == "heartbeat") {
        const auto id = string_field(payload, "board_id");
        const auto& heartbeat = payload.at("heartbeat");
        const auto& description = heartbeat.at("description");
        if (!description.is_object()) invalid("Invalid module description");
        hash_field(description, "module_sha256");
        const auto board = db.one("SELECT * FROM boards WHERE id=?", {id});
        if (board.is_null()) missing();
        // An older agent may omit identity, but cannot erase an established host binding.
        if (!heartbeat.value("physical_host_id", Json(nullptr)).is_null()) {
            const auto identity = hash_field(heartbeat, "physical_host_id");
            if (board.at("physical_host_id") != identity) {
                const auto host = host_state(db, board);
                if (!host.at("host_active_run").is_null() || host.at("host_quarantined").get<bool>()
                    || host.at("host_maintenance").get<bool>() || host.at("host_reload_pending").get<bool>())
                    conflict("Physical host identity cannot change while the old host has active or uncertain state");
                db.execute("UPDATE boards SET physical_host_id=? WHERE id=?", {identity, id});
            }
        }
        db.execute("UPDATE boards SET description=?,seen=?,reload_ack=MIN(?,reload_requested),reload_error=? WHERE id=?",
                   {description.dump(), now(), heartbeat.value("reload_ack", 0), heartbeat.value("reload_error", Json(nullptr)), id});
        auto result = db.one("SELECT reload_requested,quarantined,physical_host_id FROM boards WHERE id=?", {id});
        if (result.is_null()) missing();
        expire(db);
        dispatch_waiting(db);
        return result;
    }
    if (operation == "boards") {
        expire(db);
        dispatch_waiting(db);
        Json result = Json::array();
        const double timestamp = now();
        for (auto board : db.query("SELECT b.*,r.id AS active_run FROM boards b LEFT JOIN runs r ON b.id=r.board_id "
                                   "AND r.state IN ('queued','running','cancelling') ORDER BY b.name")) {
            board.erase("token_hash");
            board.update(host_state(db, board));
            board["description"] = parsed(board.at("description"));
            board["maintenance"] = parsed(board.at("maintenance"));
            board["status"] = board.at("host_maintenance").get<bool>() ? "maintenance"
                : board.at("host_quarantined").get<bool>() ? "quarantined"
                : timestamp - board.at("seen").get<double>() > 30 ? "offline"
                : !board.at("host_active_run").is_null() ? "busy" : board.at("host_reload_pending").get<bool>() ? "reloading" : "ready";
            result.push_back(std::move(board));
        }
        return result;
    }
    if (operation == "preflight") {
        expire(db);
        dispatch_waiting(db);
        const bool enqueue = payload.value("enqueue", false);
        auto checked = check_plan(db, payload, enqueue);
        const bool overlap = waiting_overlap(db, payload.at("plan"));
        const auto ready = check_plan(db, payload);
        checked["queueable"] = enqueue && checked.at("valid").get<bool>();
        checked["waiting_reason"] = overlap ? Json("Earlier waiting batch shares a physical host")
            : ready.at("valid").get<bool>() ? Json(nullptr) : Json(waiting_reason(ready));
        if (!enqueue && overlap) {
            checked["valid"] = false;
            checked["errors"].push_back({{"board_id", nullptr}, {"reasons", {"Earlier waiting batch shares a physical host"}}});
        }
        return checked;
    }
    if (operation == "submit") {
        expire(db);
        dispatch_waiting(db);
        const auto key = string_field(payload, "key", 128);
        const auto plan_hash = hash_field(payload, "plan_sha256");
        const bool enqueue = payload.value("enqueue", false);
        const auto previous = db.one("SELECT id,sha256,enqueue FROM batches WHERE key=?", {key});
        if (!previous.is_null()) {
            if (previous.at("sha256") != plan_hash || (previous.at("enqueue").get<int>() != 0) != enqueue)
                conflict("Idempotency key belongs to a different plan or queue intent");
            return batch_view(db, previous.at("id"));
        }
        const auto checked = check_plan(db, payload, enqueue);
        if (!checked.at("valid").get<bool>()) conflict(checked.dump());
        if (!enqueue && waiting_overlap(db, payload.at("plan"))) conflict("Earlier waiting batch shares a physical host");
        if (enqueue && db.one("SELECT COUNT(DISTINCT batch_id) AS count FROM runs WHERE state='waiting'").at("count").get<int>() >= 256)
            conflict("Waiting queue is full (256 batches)");
        const auto id = string_field(payload, "batch_id");
        const auto& runs = payload.at("run_ids");
        const auto& targets = checked.at("targets");
        if (!runs.is_array() || runs.size() != targets.size()) invalid("One run ID is required per board");
        std::set<std::string> unique_runs;
        for (const auto& run : runs) {
            if (!run.is_string() || run.get_ref<const std::string&>().empty() || run.get_ref<const std::string&>().size() > 256
                || !unique_runs.insert(run.get<std::string>()).second) invalid("Invalid or duplicate run ID");
        }
        const double timestamp = now();
        auto contract = payload;
        for (const auto* field : {"key", "batch_id", "run_ids", "enqueue"}) contract.erase(field);
        db.execute("INSERT INTO batches(id,key,plan,sha256,created,enqueue,admission_contract) VALUES(?,?,?,?,?,?,?)",
                   {id, key, payload.at("plan").dump(), plan_hash, timestamp, enqueue, contract.dump()});
        for (std::size_t index = 0; index < targets.size(); ++index)
            db.execute("INSERT INTO runs(id,batch_id,board_id,state,created,module_sha256,physical_host_key) VALUES(?,?,?,?,?,?,?)",
                       {runs[index], id, targets[index].at("board_id"), enqueue ? "waiting" : "queued", timestamp,
                        enqueue ? Json(nullptr) : targets[index].at("module_sha256"),
                        enqueue ? Json(nullptr) : targets[index].at("physical_host_key")});
        if (enqueue) dispatch_waiting(db);
        return batch_view(db, id);
    }
    if (operation == "batch") {
        expire(db);
        dispatch_waiting(db);
        return batch_view(db, string_field(payload, "batch_id"));
    }
    if (operation == "batches") {
        expire(db);
        dispatch_waiting(db);
        Json result = Json::array();
        const char* query = payload.value("real_only", false)
            ? "SELECT b.id FROM batches b WHERE EXISTS(SELECT 1 FROM runs r JOIN boards d ON d.id=r.board_id "
              "WHERE r.batch_id=b.id AND d.local=0 AND d.system_profile!='simulator' "
              "AND COALESCE(json_extract(d.description,'$.mode'),'')!='synthetic') ORDER BY b.created DESC LIMIT 100"
            : "SELECT id FROM batches ORDER BY created DESC LIMIT 100";
        for (const auto& row : db.query(query))
            result.push_back(batch_view(db, row.at("id")));
        return result;
    }
    if (operation == "poll") {
        expire(db);
        dispatch_waiting(db);
        const auto id = string_field(payload, "board_id");
        const auto board = db.one("SELECT * FROM boards WHERE id=?", {id});
        if (board.is_null()) return nullptr;
        auto row = db.one("SELECT * FROM runs WHERE board_id=? AND state IN ('queued','running','cancelling')", {id});
        if (row.is_null()) return nullptr;
        if (!demo_enabled(db) && synthetic_board(board)) {
            cancel_board(db, id, "Demo mode disabled");
            row = db.one("SELECT * FROM runs WHERE board_id=? AND state IN ('running','cancelling')", {id});
            if (row.is_null()) return nullptr;
        }
        const auto host = host_state(db, board);
        if ((host.at("host_quarantined").get<bool>() || host.at("host_maintenance").get<bool>()) && row.at("state") != "cancelling") return nullptr;
        const bool claimed = row.at("state") == "queued";
        if (claimed) {
            const auto description = parsed(board.at("description"), Json::object());
            if (description.value("module_sha256", Json(nullptr)) != row.at("module_sha256")) {
                db.execute("UPDATE runs SET state='failed',finished=?,result=? WHERE id=?",
                           {now(), Json{{"error", "module changed after admission; submit again"}}.dump(), row.at("id")});
                return nullptr;
            }
            db.execute("UPDATE runs SET state='running',started=? WHERE id=?", {now(), row.at("id")});
            row = db.one("SELECT * FROM runs WHERE id=?", {row.at("id")});
        }
        auto result = run_view(std::move(row));
        result["claimed"] = claimed;
        result["plan"] = parsed(db.one("SELECT plan FROM batches WHERE id=?", {result.at("batch_id")}).at("plan"));
        return result;
    }
    if (operation == "finish") {
        const auto id = string_field(payload, "run_id");
        auto row = db.one("SELECT * FROM runs WHERE id=? AND board_id=?", {id, string_field(payload, "board_id")});
        if (row.is_null()) missing();
        const auto& completion = payload.at("completion");
        if (row.at("state") == "queued" || row.at("state") == "waiting") conflict("Run must be claimed before completion");
        if (hash_field(completion, "module_sha256") != row.at("module_sha256").get<std::string>()) conflict("Module generation mismatch");
        const auto state = row.at("state").get<std::string>();
        if (state == "succeeded" || state == "failed" || state == "cancelled") return run_view(std::move(row));
        const bool clean = completion.at("cleanup_ok").get<bool>();
        auto final_state = string_field(completion, "state", 16);
        if (final_state != "succeeded" && final_state != "failed" && final_state != "cancelled") invalid("Invalid completion state");
        if (!completion.at("result").is_object()) invalid("Completion result must be an object");
        if (state == "lost") {
            auto evidence = parsed(row.at("result"), Json::object());
            if (!evidence.contains("late_completion")) {
                evidence["late_completion"] = completion;
                evidence["late_completion"]["received"] = now();
                db.execute("UPDATE runs SET result=? WHERE id=?", {evidence.dump(), id});
            }
            // Retain execution evidence without treating late arrival as administrative recovery.
            return run_view(db.one("SELECT * FROM runs WHERE id=?", {id}));
        }
        if (state == "cancelling" && clean) final_state = "cancelled";
        if (!clean) {
            final_state = "failed";
            db.execute("UPDATE boards SET quarantined=1 WHERE id=?", {payload.at("board_id")});
        }
        db.execute("UPDATE runs SET state=?,finished=?,result=? WHERE id=?",
                   {final_state, now(), completion.at("result").dump(), id});
        dispatch_waiting(db);
        return run_view(db.one("SELECT * FROM runs WHERE id=?", {id}));
    }
    if (operation == "cancel") {
        const auto id = string_field(payload, "batch_id");
        if (db.one("SELECT 1 FROM batches WHERE id=?", {id}).is_null()) missing();
        db.execute("UPDATE runs SET state='cancelled',finished=?,result=? WHERE batch_id=? AND state IN ('waiting','queued')",
                   {now(), Json{{"code_executed", false}, {"cleanup_ok", true}}.dump(), id});
        db.execute("UPDATE batches SET waiting_reason=NULL WHERE id=?", {id});
        db.execute("UPDATE runs SET state='cancelling' WHERE batch_id=? AND state='running'", {id});
        expire(db);
        dispatch_waiting(db);
        return batch_view(db, id);
    }
    if (operation == "board_action") {
        const auto id = string_field(payload, "board_id");
        const auto action = string_field(payload, "action", 16);
        const auto board = db.one("SELECT * FROM boards WHERE id=?", {id});
        if (board.is_null()) missing();
        if (action == "reload" || action == "force-reload") {
            db.execute("UPDATE boards SET reload_requested=reload_requested+1,reload_error=NULL WHERE id=?", {id});
            if (action == "force-reload")
                for (const auto& member : host_members(db, board)) cancel_board(db, member.at("id"), "Forced physical host module reload");
        }
        else if (action == "recover") {
            const auto host = host_state(db, board);
            if (host.at("host_maintenance").get<bool>()) conflict("Restart maintenance must complete before recovery");
            if (!host.at("host_active_run").is_null()) conflict("Physical host active run must be stopped before recovery");
            db.execute("UPDATE boards SET quarantined=0 WHERE id=?", {id});
        } else if (action == "restart") {
            const auto host = host_state(db, board);
            if (!host.at("host_active_board_id").is_null() && host.at("host_active_board_id") != id)
                conflict("Sibling target has an active run; guest restart cannot prove its cleanup");
            if (host.at("host_maintenance").get<bool>() && board.at("maintenance").is_null())
                conflict("Physical host restart maintenance is already pending");
            auto maintenance = parsed(board.at("maintenance"));
            if (maintenance.is_null()) {
                const auto description = parsed(board.at("description"), Json::object());
                Json runs = Json::array();
                for (const auto& run : db.query("SELECT id FROM runs WHERE board_id=? AND state IN ('queued','running','cancelling')", {id}))
                    runs.push_back(run.at("id"));
                maintenance = {{"restart_id", string_field(payload, "restart_id", 64)}, {"started", now()},
                               {"previous_quarantined", board.at("quarantined").get<int>() != 0}, {"run_ids", runs},
                               {"mode", description.value("mode", std::string())},
                               {"cleanup_scope", description.value("cleanup_scope", std::string("external"))}};
                db.execute("UPDATE boards SET maintenance=?,quarantined=1 WHERE id=?", {maintenance.dump(), id});
                cancel_board(db, id, "Guest restart requested");
            }
            return {{"board_id", id}, {"action", action}, {"restart_id", maintenance.at("restart_id")}};
        } else if (action == "restart-complete") {
            const auto maintenance = parsed(board.at("maintenance"));
            if (maintenance.is_null() || maintenance.at("restart_id") != string_field(payload, "restart_id", 64))
                conflict("Restart maintenance identity mismatch");
            const auto before = string_field(payload, "boot_id_before", 64), after = string_field(payload, "boot_id_after", 64);
            if (before == after || !payload.value("agent_ready", false)) conflict("Fresh guest boot and agent readiness are required");
            if (maintenance.at("mode") != "linux-process" || maintenance.at("cleanup_scope") != "process-group")
                conflict("Guest reboot cannot confirm this module's external resource cleanup");
            Json evidence = {{"restart_id", maintenance.at("restart_id")}, {"instance_id", string_field(payload, "instance_id", 64)},
                             {"boot_id_before", before}, {"boot_id_after", after}, {"cleanup_ok", true}, {"agent_ready", true}};
            for (const auto& run_id : maintenance.at("run_ids")) {
                const auto run = db.one("SELECT state,result FROM runs WHERE id=? AND board_id=?", {run_id, id});
                if (run.is_null()) continue;
                auto result = parsed(run.at("result"), Json::object());
                result["restart_cleanup"] = evidence;
                const auto state = run.at("state");
                if (state == "queued" || state == "running" || state == "cancelling") {
                    result["error"] = "Experiment interrupted by verified guest restart";
                    result["cleanup_ok"] = true;
                    db.execute("UPDATE runs SET state='cancelled',finished=?,result=? WHERE id=?", {now(), result.dump(), run_id});
                } else db.execute("UPDATE runs SET result=? WHERE id=?", {result.dump(), run_id});
            }
            db.execute("UPDATE boards SET maintenance=NULL,quarantined=? WHERE id=?", {maintenance.at("previous_quarantined"), id});
            return {{"board_id", id}, {"action", action}, {"restart_id", maintenance.at("restart_id")}, {"cleanup", evidence},
                    {"quarantined", maintenance.at("previous_quarantined")}};
        } else invalid("Unknown board action");
        dispatch_waiting(db);
        return {{"board_id", id}, {"action", action}};
    }
    invalid("Unknown core operation");
}

char* allocate_response(const Json& value) {
    const auto text = value.dump();
    auto* output = static_cast<char*>(std::malloc(text.size() + 1));
    if (!output) return nullptr;
    std::memcpy(output, text.c_str(), text.size() + 1);
    return output;
}
} // namespace

extern "C" int sg_core_abi_version(void) { return 1; }

extern "C" char* sg_core_call(const char* db_path, const char* operation, const char* payload_json) {
    try {
        Json response;
        try {
            if (!db_path || !*db_path || !operation || !payload_json || std::strlen(operation) > 64
                || std::strlen(payload_json) > 8 * 1024 * 1024) invalid("Invalid core call arguments");
            const auto payload = Json::parse(payload_json);
            if (!payload.is_object()) invalid("Core payload must be an object");
            Database database(db_path);
            // WAL mode is persistent and must be selected before opening the schema transaction.
            if (std::string_view(operation) == "init") database.execute("PRAGMA journal_mode=WAL");
            database.begin();
            auto value = dispatch(database, operation, payload);
            database.commit();
            response = {{"ok", true}, {"value", std::move(value)}};
        } catch (const Error& error) {
            response = {{"ok", false}, {"error", {{"kind", error.kind}, {"message", error.what()}}}};
        } catch (const Json::exception&) {
            response = {{"ok", false}, {"error", {{"kind", "invalid"}, {"message", "Invalid core JSON payload"}}}};
        } catch (const std::exception&) {
            response = {{"ok", false}, {"error", {{"kind", "internal"}, {"message", "Core operation failed"}}}};
        } catch (...) {
            response = {{"ok", false}, {"error", {{"kind", "internal"}, {"message", "Unknown core failure"}}}};
        }
        return allocate_response(response);
    } catch (...) {
        return nullptr; // Even allocation failure cannot propagate through a C ABI.
    }
}

extern "C" void sg_core_free(char* result) { std::free(result); }
