# Tasks

## 1. Physical resource admission

- [x] 1.1 Implement additive native physical-host grouping, FIFO contention, maintenance/quarantine/recovery gates and memory overhead checks; verify cross-target conflicts, identity changes, legacy compatibility and restart regression tests.
- [x] 1.2 Implement native host sampling and delegated cgroup CPU/memory scopes with explicit capability/enforcement evidence; verify parsers, limits, failure cleanup and a real Linux resource scope.

## 2. Durable operation

- [x] 2.1 Persist agent claims and completion outbox with process identity and instance locking; test acknowledgement loss, agent restart, unknown cleanup and duplicate execution prevention.
- [x] 2.2 Add local supervised controller/tunnel CLI and Linux deployment delegation; verify generated service definitions, status privacy and actual local service restart/reconnection.
- [x] 2.3 Document grouping, recovery, resource policies and supervised operation in English with equivalent README entries; check examples against implemented CLI/API.

## 3. Device observability

- [x] 3.1 Add bounded telemetry storage and reader-authorized HTTP/CLI/MCP retrieval; test missing values, stale receipt time, retention, identity and allocation views.
- [x] 3.2 Add measured device monitoring and shared-host occupancy to the console; verify actual samples, stale/unavailable states, desktop and narrow layouts and interaction checks.
- [x] 3.3 Add a reusable English operator skill and CLI/MCP reference for capability discovery, prepared environments, idempotent admission, measured telemetry and evidence-based recovery; validate its metadata, links and implemented tool contracts.

## 4. Integrated verification

- [ ] 4.1 Deploy privately to the existing Pi and verify telemetry, physical-host admission, process-tree resource controls, recovery evidence and offline KVM execution without publishing private inventory or backups.
- [ ] 4.2 Run Python/native regression tests and strict OpenSpec validation, inspect publication privacy, and publish reviewed changes with the repository owner's identity.

## Verification notes

- The existing controller and SSH tunnel retain their foreground/manual deployment at the user's request. Controller crash recovery and tunnel reconnection were exercised with isolated macOS services, which were subsequently uninstalled.
- Native cgroup CPU placement, aggregate memory enforcement, OOM handling, descendant cleanup and scope removal passed in a real ARM64 Linux QEMU guest.
- The connected Pi passed offline KVM execution, fresh-root output, measured telemetry, allocation visibility and cleanup checks. Its current user service lacks cpuset delegation, so explicit cgroup admission is rejected; on-Pi process-tree enforcement remains pending administrator provisioning.
- Monitoring was checked at desktop and narrow widths with actual Pi measurements and with an older agent that has no telemetry.
