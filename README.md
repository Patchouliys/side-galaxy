<p align="center"><img src="src/side_galaxy/static/icon.svg" width="88" alt="Side Galaxy icon"></p>
<h1 align="center">Side Galaxy · 侧视星系</h1>
<p align="center">One orbit. Many worlds.<br>A modular control plane for embedded boards and multicore experiments.</p>
<p align="center"><strong>English</strong> · <a href="README.zh-CN.md">简体中文</a></p>

Manage multiple embedded boards from one server. Upload experiment code, select target devices, configure resources, and collect results through a shared Web, CLI, or MCP workflow.

Side Galaxy includes Raspberry Pi 4 / Pi 5 profiles and Linux / KVM execution modules. Board descriptions, system profiles, and execution modules can be extended independently. Modules reload between experiments while running tasks keep their pinned versions.

## Features

- **Run your own code:** ZIP bundles contain setup steps, a launch command, environment defaults, and output declarations. Add arguments and environment overrides for each experiment.
- **Manage a fleet:** capability discovery, reserved CPU checks, atomic batch admission, per-board leases, idempotent submission, cancellation, and recovery.
- **Control runtime resources:** Linux process affinity and address-space limits; KVM live vCPU affinity, guest execution through QEMU Guest Agent, statistics, and affinity restoration.
- **Trace every run:** artifact and module hashes, resource plans, exit codes, final logs, output files, and cleanup evidence.
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
uv run sg serve --demo
```

Open [localhost:7980](http://127.0.0.1:7980) and enter the console. Demo boards generate synthetic results and do not execute uploaded code.

In another terminal:

```sh
uv run sg boards
uv run sg preflight examples/pi-contention.json
uv run sg submit examples/pi-contention.json --key first-experiment
uv run sg batches
```

## Develop without hardware

Start the control server, then run `uv run sg lab up` in another terminal. The local QEMU lab boots ARM64 Linux, builds the native core inside the guest, and registers a target that actually compiles and runs uploaded experiments. See the [local lab guide](docs/local-lab.md) for prerequisites and options.

Select another target to reuse the same artifact and parameters, or run `sg replay SOURCE_BATCH_ID --boards TARGET_BOARD_ID --key deployment-001`. Declared architecture, OS, and command requirements are checked before admission.

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

## Connect AI tools

Configure a compatible MCP client to run `sg mcp`, with `SG_SERVER` and `SG_TOKEN` in its environment. Queries and preflight are available by default. Use `sg mcp --allow-writes` with an operator token to upload artifacts, submit experiments, cancel batches, or reload modules.

## Documentation

The detailed guides are written in English.

- [QEMU lab and experiment migration](docs/local-lab.md)
- [Native core build and packaging](docs/native-build.md)
- [Deployment and AI integration](docs/operations.md)
- [Experiment bundles, dependencies, and results](docs/workloads.md)
- [Linux / KVM execution and guest setup](docs/kvm-workloads.md)
- [Module development and hot reload](docs/modules.md)
- [Architecture and resource model](docs/research.md)
- [Tests and checks](docs/testing.md)
- [Brand and interface design](docs/brand.md)

## License

[MIT](LICENSE). Bundled third-party components retain their original licenses; see [THIRD_PARTY.md](THIRD_PARTY.md).
