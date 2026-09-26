# Proposal

## Why

Side Galaxy unifies resource planning, batch experiments, and AI access across embedded development boards, avoiding a full board reboot for every test. Initial board profiles support Raspberry Pi 4 and Pi 5 and allow management modules to be hot-reloaded during development.

## What Changes

- Establish Chinese research documentation, a phased roadmap, and side-view galaxy brand assets.
- Manage boards, online status, resource plans, batch jobs, and results from one server through Web, CLI, and MCP.
- Include an explicitly identified simulated cluster with independent polling agents, plus a Linux unprivileged process experiment module and a KVM module for live affinity, statistics, and restoration.
- Provide replaceable Pi 4 and Pi 5 profiles and content-addressed management modules that reload between tasks while running tasks pin their generation.
- Implement atomic batch preflight, idempotency, conflict prevention, cancellation, and quarantine after agent loss, retaining results and resource-plan digests.
- Provide multi-device inventories and an Ansible entry point; verify only local workflows when board connection details are unavailable.
- Create a public GitHub repository using a project identity and remove sensitive data before committing.

## Capabilities

### New Capabilities

- `fleet-control`: Multi-board resource planning, task lifecycle, scoped identities, and recovery.
- `module-runtime`: Pi profiles, execution-module discovery, content-addressed hot reload, and evidence.
- `operator-interfaces`: Side Galaxy Web, CLI, MCP, and deployment entry points.

### Modified Capabilities

No existing capabilities.

## Impact

Add a Python control plane, SQLite state store, same-origin static frontend, official Python MCP SDK, independent agents, Ansible deployment, and an OpenSpec workflow. Linux with KVM is confirmed; the KVM module uses libvirt/virsh to manage an explicitly configured experiment VM. Physical-board acceptance, hardware QoS, real-time guarantees, multi-tenancy, and high availability will be addressed separately.

## User Addition: Real Experiment Bundles

The user explicitly requires experiment code to travel through the platform to boards, beyond built-in parameter templates. Add versioned ZIP artifacts, structured launch commands, arguments, and environment variables, distribution and execution on Linux and KVM guests, and returned logs and output files. Trusted experiment code may declare its own setup/run commands; it does not replace management plugins through remote module-source uploads.
