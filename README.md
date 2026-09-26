<p align="center"><img src="src/side_galaxy/static/icon.svg" width="88" alt="Side Galaxy icon"></p>
<h1 align="center">Side Galaxy</h1>
<p align="center">One orbit. Many worlds.<br>A modular control plane for embedded multi-board experiments and virtualization resources.</p>

One server manages boards centrally, with Web, CLI, and MCP for experiment preflight, execution, and traceability. The initial board profiles target Raspberry Pi 4 / Pi 5, with Linux + KVM as the system direction.

**Current version: a runnable 0.1 prototype.** The local synthetic fleet, HTTP, CLI, MCP, and module hot reload have been verified; Linux / KVM execution modules are implemented, but deployment on real Pi hardware and isolation behavior have not passed acceptance testing. CPU affinity does not imply exclusive cores, cache isolation, or hard real-time guarantees.

## Quick Start

Requires Python 3.11+ and uv:

```sh
uv sync --frozen
uv run sg serve --demo
```

Open `http://127.0.0.1:7980`, select boards, and launch an experiment. Demo data is explicitly marked synthetic.

```sh
uv run sg boards
uv run sg preflight examples/pi-contention.json
uv run sg submit examples/pi-contention.json --key first-experiment
uv run sg batches
```

## Implemented

- An edge-on galaxy interface with deep-space blue and a cyan core, original SVG icons, and responsive board and experiment views.
- Board/system profiles, trusted execution modules in separate processes, content-hash version pinning, and hot reload at idle boundaries.
- Atomic multi-board admission, reserved-core checks, leases, idempotency, cancellation acknowledgement, lost-agent quarantine, and JSON results.
- Linux process experiments; live vCPU affinity, statistics, and original-configuration restoration for selected KVM VMs.
- Per-board agent tokens, operator/read roles, a same-origin interface, CLI, and MCP stdio implemented with the official SDK.
- Container control-plane configuration and an Ansible entry point for multi-board agent deployment (not deployed on an actual server or boards).

## Documentation

- [Research and implementation checklist](docs/research.md): resource-management scope, approach comparison, reboot-free boundaries, roadmap, and official sources.
- [Modules and hot reload](docs/modules.md): protocols and extensions for new board profiles, systems, and execution modules.
- [Operations, deployment, and AI integration](docs/operations.md): the server, Pi + KVM, Ansible, CLI, and MCP.
- [Verification record](docs/verification.md): the boundary between local verification and unverified real hardware.
- [Brand guide](docs/brand.md): icon, logo, and theme.

## Development

```sh
uv run python -m unittest discover -s tests -v
npm ci --ignore-scripts
npm run spec:validate
# After starting --demo in another terminal:
uv run python scripts/check_integration.py
```

OpenSpec 1.13.2 manages proposal / specs / design / tasks under `openspec/`; the Ponytail skill is pinned to `.agents/skills/ponytail`. Project commands disable telemetry. Define capabilities and acceptance criteria before adding the smallest implementation; synthetic results are not evidence from real hardware.

MIT · Side Galaxy contributors. Public code includes third-party skills and their original licenses; it excludes real device addresses, access credentials, and runtime databases.
