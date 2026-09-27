# Design

## Context

The current scheduler grants leases per target ID, the agent keeps claims and completions in memory, and the local controller runs as a foreground process. Linux and KVM execution paths already expose cleanup evidence. Workload children may create separate sessions, so losing a module process cannot prove that every experiment child stopped.

## Goals / Non-Goals

**Goals:** Keep services supervised, prevent physical-host double allocation, persist completion evidence, and display real host measurements and resource enforcement.

**Non-Goals:** Same-host concurrent experiments, automatic physical power cycling, live VM adoption after an unjournaled crash, privileged resource changes without delegation, or guaranteed cache/interrupt isolation.

## Decisions

- Add optional hashed physical host identity to heartbeat and persist immutable admitted host keys. Group admission, FIFO contention and quarantine by that key. Legacy unidentified targets retain per-target semantics and explicitly report unknown identity. Do not change identity while the old host has active or uncertain state. A guest restart cannot prove sibling cleanup.
- Persist private claims before staging or launch and completion before network acknowledgement. Gate execution on writing process identity and applying resource controls. Use an OS-local per-board advisory lock. Replay completion acknowledgements after restart; never replay experiment execution. Interrupted external resources and workload processes remain uncertain unless durable completion or stronger verified scope evidence exists.
- A C++ host helper reads bounded Linux proc/sys counters and delegated cgroup controls. Python bridges samples into authenticated bounded history every five seconds. Missing values remain null; server receipt time determines freshness despite board clock skew. A stable host identity is hashed before transmission; raw serials, machine IDs and filesystem paths are never telemetry.
- Use delegated cgroup v2 for aggregate experiment memory and CPU placement when available. The explicit cgroup policy rejects unsupported targets, while auto policy reports the actual enforcement mode. VM guest RAM plus a declared host overhead budget determines the aggregate limit. Retain existing affinity and guest RAM configuration. Verify cgroup emptiness before deleting it or asserting cleanup.
- Use native operating-system service managers rather than a custom daemon supervisor. Provide macOS user launch agents and Linux user services through a local-only CLI. An SSH tunnel service references an existing private SSH config; it cannot accept host shell commands. Read-only service health reports management state and controller reachability without exposing paths or secrets.
- Reuse the existing console for device monitoring, measured trends, stale indicators and physical-host allocations. Web, CLI and MCP read the same endpoint. Retain bounded samples and avoid database writes on every UI read.

## Risks / Trade-offs

- [Unknown crash window] Preserve uncertainty and quarantine instead of inventing cleanup evidence.
- [Missing cgroup delegation] Report unavailable and reject explicit cgroup policy; provision delegation administratively.
- [Cloned machine identity] Permit administrator-assigned unique host identity and show grouping in the console; never infer physical ownership from a display name.
- [Service update during an experiment] Check active work before replacing the controller or agent; test restarts with explicit recoverable cases.
- [Transient measurements] Distinguish measured values, missing sensors, stale data and synthetic targets.

## Migration Plan

Use additive database fields and optional heartbeat data. Upgrade agents at idle to establish host identity before admitting grouped work. Preserve legacy idempotency hashes for default new plan fields. Save private database/service backups before local deployment and retain the prior executable configuration for recovery.
