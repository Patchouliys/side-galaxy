<p align="center"><img src="src/side_galaxy/static/icon.svg" width="88" alt="Side Galaxy icon"></p>
<h1 align="center">Side Galaxy · 侧视星系</h1>
<p align="center">One orbit. Many worlds.<br>A modular control plane for embedded boards and multicore experiments.</p>
<p align="center"><strong>English</strong> · <a href="README.zh-CN.md">简体中文</a></p>

Manage multiple embedded boards from one server. Upload experiment code, select target devices, configure resources, and collect results through a shared Web, CLI, or MCP workflow.

Side Galaxy includes Raspberry Pi 4 / Pi 5 profiles and Linux / KVM execution modules. Board descriptions, system profiles, and execution modules can be extended independently. Modules reload between experiments while running tasks keep their pinned versions.

## Features

- **Run your own code:** ZIP bundles contain setup steps, a launch command, environment defaults, and output declarations. Add arguments and environment overrides for each experiment.
- **Manage a fleet:** capability discovery, reserved CPU checks, atomic batch admission, persistent waiting queues, per-target leases, idempotent submission, cancellation, and recovery.
- **Bring an offline environment:** distribute prepared guest images and dependencies, then give each experiment a fresh writable layer without restarting the board.
- **Control runtime resources:** Linux process affinity and address-space limits; KVM live vCPU affinity, guest execution through QEMU Guest Agent, statistics, and affinity restoration.
- **Trace every run:** artifact, environment, and module hashes, resource plans, running output, exit codes, final logs, output files, and cleanup evidence.
- **Connect people and AI:** a Web console, scriptable CLI, and MCP stdio tools use the same API and authorization rules.
- **Deploy centrally:** a containerized control server and an Ansible playbook for Debian-family board agents.

## Architecture

The C++20 core uses SQLite for board registration, capability admission, atomic batches, leases, and task-state transitions. Python bridges HTTP, CLI, and MCP to that core, handles artifact I/O, and hosts the execution-plugin protocol.

The native core is required; there is no Python scheduling fallback. Board and system support remains in profiles and execution modules.

## Quick start

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/). Building from source also requires CMake 3.20+, a C++20 compiler, and SQLite development headers.

| Platform | Build prerequisites |
|---|---|
| macOS | Xcode Command Line Tools (`xcode-select --install`) and CMake |
| Debian / Ubuntu | `sudo apt-get install build-essential cmake libsqlite3-dev` |

`uv sync` builds the required native library. See [native build instructions](docs/native-build.md) for toolchain setup and platform-specific packages.

```sh
uv sync --frozen
uv run sg serve
```

Open [localhost:7980](http://127.0.0.1:7980) and enter the console. The default workspace shows real connected targets. Use `sg lab up` for local Linux execution, or enable **Demo mode** in the console to explore synthetic samples. Local access stays loopback-only; remote listeners require `SG_TOKEN`.

In another terminal:

```sh
uv run sg boards
uv run sg lab up
uv run sg batches
```

## Develop without hardware

Start the control server, then run `uv run sg lab up` in another terminal. The local QEMU lab boots ARM64 Linux, builds the native core inside the guest, and registers a target that actually compiles and runs uploaded experiments. See the [local lab guide](docs/local-lab.md) for prerequisites and options.

Select another target to reuse the same artifact and parameters, or run `sg replay SOURCE_BATCH_ID --boards TARGET_BOARD_ID --key deployment-001`. Declared architecture, OS, and command requirements are checked before admission.

## Experiment controls

Use `sg preflight plan.json --enqueue` and `sg submit plan.json --enqueue --key experiment-001` to wait for busy targets. Each execution target runs one experiment at a time; independent targets run in parallel. A waiting batch holds no resources and receives all required leases atomically after fresh checks. The console enables queuing by default. `waiting` means awaiting resources; `queued` means admitted and awaiting the agent. Queue position is not an ETA.

Follow a run with `sg logs RUN_ID --follow`; press Ctrl+C to stop reading. Live output is bounded and reports truncation. Final stdout/stderr and results remain independent of live delivery.

Use `sg reload BOARD_ID` to reload after current work, or `sg reload BOARD_ID --force` to interrupt it first. The console exposes both actions with progress and failure feedback. Managed QEMU guests also support `sg lab restart` and `sg lab restart --force`; watch completion with `sg labs`. Restart preserves the disk and device identity.

The demo switch starts/stops sample agents and hides synthetic-only inventory/history without deleting records. It is also available as `sg workspace --demo on|off`; `sg serve --demo` explicitly starts with samples enabled.

## Bring your experiment

An experiment ZIP contains `experiment.json` at its root alongside the code and input files:

```json
{
  "schema": 1,
  "name": "latency-benchmark",
  "setup": [],
  "run": ["python3", "benchmark.py"],
  "env": {"SAMPLES": "1000"},
  "outputs": ["results.json"]
}
```

Package and upload the included example:

```sh
mkdir -p .data
uv run sg pack examples/hello-workload --output .data/hello-workload.zip
uv run sg artifact-upload .data/hello-workload.zip
```

Select the uploaded version and target boards in the console, or submit a JSON plan with the CLI or MCP. Code runs on connected Linux agents or configured KVM guests; see the [experiment guide](docs/workloads.md) for plans, dependencies, logs, and downloads.

## Prepared offline environments

Prepare a guest containing Python, QEMU Guest Agent, and the tools your experiment needs. Package and upload it separately from the experiment code:

```sh
uv run sg environment-pack prepared-environment --output .data/environment.zip
uv run sg environment-upload .data/environment.zip
uv run sg environments
```

Select the environment in the console or set its digest as `environment_sha256` in a workload plan. The `qemu-environment` target requires administrator-provided QEMU and KVM access on Linux. The board downloads packages from the controller, with no Internet access required. Every run, including a replay, starts from a fresh writable overlay; guest cleanup resets it without rebooting the board. See the [environment guide](docs/environments.md) for image preparation and the [deployment guide](docs/operations.md) for private offline bootstrap. Use `linux-process` for initial experiments in a physical board's existing OS.

## Connect AI tools

Configure a compatible MCP client to run `sg mcp`, with `SG_SERVER` and `SG_TOKEN` in its environment. Queries and preflight are available by default, including `list_environments` and `get_run_logs`. Use `sg mcp --allow-writes` with an operator token to upload experiment or environment packages, submit experiments with `run_experiment(..., enqueue=true)`, cancel batches, or reload modules.

## Documentation

The detailed guides are written in English.

- [QEMU lab and experiment migration](docs/local-lab.md)
- [Native core build and packaging](docs/native-build.md)
- [Deployment and AI integration](docs/operations.md)
- [Experiment bundles, dependencies, and results](docs/workloads.md)
- [Prepared offline environments](docs/environments.md)
- [Linux / KVM execution and guest setup](docs/kvm-workloads.md)
- [Module development and hot reload](docs/modules.md)
- [Architecture and resource model](docs/research.md)
- [Tests and checks](docs/testing.md)
- [Brand and interface design](docs/brand.md)

## License

[MIT](LICENSE). Bundled third-party components retain their original licenses; see [THIRD_PARTY.md](THIRD_PARTY.md).
