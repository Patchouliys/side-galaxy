# Proposal

## Why

Side Galaxy unifies resource planning, batch experiments, and AI access across embedded development boards without requiring a full board reboot for each test. Initial board profiles cover Raspberry Pi 4 and Pi 5, with management modules that can be hot-reloaded during development.

## What Changes

- Deliver Chinese research documentation, a phased roadmap, and branding based on a galaxy viewed from the side.
- Provide a single server for board inventory, availability, resource plans, batch jobs, and results through Web, CLI, and MCP interfaces.
- Include an explicitly labeled simulated cluster and independent agents that poll the server, plus a Linux unprivileged process module and a KVM module for live affinity, statistics, and restoration.
- Make Pi 4 and Pi 5 board profiles replaceable. Address management modules by content hash, reload them between jobs, and pin running jobs to their original generation.
- Implement atomic batch admission, idempotency, conflict prevention, cancellation, and quarantine after agent loss, while retaining results and resource-plan hashes.
- Provide inventory examples and Ansible entry points for multiple devices.
- Create a public GitHub repository using the repository owner's GitHub identity and exclude host-local identifiers, private inventory, and credentials.
- Support versioned ZIP experiment bundles, structured commands, arguments, environment variables, Linux and KVM guest execution, and returned logs and output files.

## Capabilities

### New Capabilities

- `fleet-control`: Resource planning across boards, job lifecycle, scoped identities, and recovery.
- `module-runtime`: Pi board profiles, execution capability discovery, content-addressed hot reload, and execution evidence.
- `operator-interfaces`: Side Galaxy Web, CLI, MCP, and deployment entry points.

### Modified Capabilities

None. There are no existing capabilities to modify.

## Impact

Add a Python control plane, SQLite state store, same-origin static frontend, official Python MCP SDK, independent agents, Ansible deployment, and an OpenSpec workflow. Linux with KVM is the selected virtualization platform; the KVM module uses libvirt and virsh to manage an explicitly configured experiment VM. Hardware QoS, real-time scheduling, multi-tenancy, and high availability are outside this change.

## Experiment Bundles

Experiment code travels through the platform to the selected boards instead of being limited to built-in parameter templates. Bundles declare trusted `setup` and `run` commands and return logs and output files. Uploading experiment code does not replace management modules or expose an API for uploading their source.
