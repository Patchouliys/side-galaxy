# Proposal

## Why

Physical boards connected only by USB need complete offline experiment environments, rather than network-dependent installation. Operators also need durable waiting queues and running logs while preserving atomic admission and cleanup evidence.

## What Changes

- Add content-addressed, offline VM environment bundles containing a prepared root disk and boot files, with bounded streaming transfer and digest verification.
- Add a modular QEMU environment backend that boots a fresh writable overlay for each experiment, runs uploaded workloads through a preinstalled guest agent, and resets by removing only verified stopped instances.
- Add opt-in persistent FIFO queues with atomic whole-batch admission, overlap fairness, cancellation, and dispatch-time capability checks in the C++ core.
- Add bounded running log delivery through authenticated agent and reader APIs, CLI, MCP, and the console.
- Preserve uncertain-cleanup quarantine and late completion evidence; validate the Linux workflow on the connected physical board and distinguish actual KVM execution from other accelerators.

## Capabilities

### New Capabilities

- `offline-environments`: Portable prepared guest packages and per-experiment VM lifecycle without board internet access.
- `experiment-queue`: Durable waiting requests and atomic fair dispatch.
- `running-logs`: Bounded incremental experimental output across agent, API, CLI, MCP, and console.

### Modified Capabilities

None. Existing requirements remain in the earlier active changes; these additions preserve their admission and cleanup rules.

## Impact

C++ scheduling and SQLite migrations, Python transport and trusted execution adapters, new system profiles, command interfaces, and console experiment controls. QEMU is an administrator-provided native runtime. No OCI compatibility claim, custom hypervisor, kernel isolation implementation, automatic privilege escalation, or physical-board reboot is introduced.
