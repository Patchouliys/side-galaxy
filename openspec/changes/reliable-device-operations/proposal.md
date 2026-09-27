# Proposal

## Why

Offline experiments now run on physical KVM targets, but controller lifetime, agent crashes, and duplicate execution targets on the same hardware still need explicit operational handling. Operators also need actual device measurements and resource occupancy in the console.

## What Changes

- Add durable agent claim/completion recovery and single-agent locking without automatically rerunning uncertain work.
- Provide supervised local controller and SSH tunnel services, health checks, and Linux deployment defaults for restart and resource delegation.
- Collect native Linux host measurements, retain bounded history, and expose the same monitoring data in Web, CLI, and MCP.
- Group execution targets by private hashed physical identity in native admission, enforcing one experiment per physical host and propagating occupancy and quarantine gates.
- Add delegated cgroup CPU placement and process-tree memory budgets where supported, with explicit capability and cleanup evidence; budget QEMU host overhead separately.

## Capabilities

### New Capabilities
- `durable-agent-recovery`: Persisted claims, completion retry, instance locking, conservative reconciliation.
- `device-observability`: Bounded actual measurements and operator monitoring interfaces.
- `physical-resource-admission`: Shared physical-host occupancy, fair admission and resource enforcement.
- `supervised-services`: Persistent local controller/tunnel operation and service health.

### Modified Capabilities

None. Existing change specifications are not yet archived into main specifications.

## Impact

C++ host sampling/resource helpers and scheduler, agent lifecycle, additive SQLite storage, HTTP/CLI/MCP interfaces, console, deployment templates and bilingual documentation. No new third-party runtime dependency. Private identities, service configuration, device samples and test evidence stay outside Git.
