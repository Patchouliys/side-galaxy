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

## Quick start

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

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

- [Deployment and AI integration](docs/operations.md)
- [Experiment bundles, dependencies, and results](docs/workloads.md)
- [Linux / KVM execution and guest setup](docs/kvm-workloads.md)
- [Module development and hot reload](docs/modules.md)
- [Architecture and resource model](docs/research.md)
- [Tests and checks](docs/testing.md)
- [Brand and interface design](docs/brand.md)

## License

[MIT](LICENSE). Bundled third-party components retain their original licenses; see [THIRD_PARTY.md](THIRD_PARTY.md).
