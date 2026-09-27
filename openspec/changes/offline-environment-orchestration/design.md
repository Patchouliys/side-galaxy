# Design

## Context

The native engine grants one active lease per execution target. Existing agents can execute bundles in Linux processes or a preconfigured libvirt guest, but do not distribute complete VM environments. Artifact transfer is limited to small experiment ZIPs. USB-connected physical boards have no Internet route and administrator privileges are not assumed.

## Goals / Non-Goals

**Goals:** Reproducible offline guest deployment, persistent fair queuing, bounded live output, physical Linux validation, and explicit accelerator evidence.

**Non-Goals:** Building a hypervisor or OCI runtime, claiming container compatibility, sharing one target lease between independent experiments, automatic package downloads on the board, and rebooting the physical host as an environment reset.

## Decisions

- Keep one experiment per execution target and parallelism across independent targets. Built-in victim/interferer workloads retain their internal parallel workers. C++ owns queued admission; waiting batches own no resources. Add an opt-in enqueue parameter, leaving immediate admission compatible. Admit every target in a batch together, preserve order for overlapping targets, and allow disjoint batches to progress.
- Persist the validated artifact and environment contracts with waiting requests. Recheck target availability, capabilities and generation at dispatch. Keep quarantine until explicit evidence-backed recovery. Preserve late completion evidence without converting lost jobs into success.
- Environment ZIPs hold a manifest, a raw root disk, and either direct-boot kernel/initrd or firmware. Explicit file names, streamed size and digest checks, no links, and raw-only base disks prevent arbitrary extraction and external backing-file references. Store immutable objects by digest. Each experiment creates its own qcow2 writable overlay and private QMP/QGA sockets.
- Use QEMU/KVM as an administrator-deployed execution module. The prepared guest contains Python and QEMU Guest Agent; no runtime Internet or guest package installation is needed. Pin host CPU affinity, set VM RAM, expose no host directories and no guest network by default. Reuse the existing guest workload transfer/cleanup protocol. Verify instance identity and process exit before removing an overlay. A new run is a clean reset.
- Stream bounded log events from trusted execution modules through an inherited pipe to the agent, with sequence-based idempotent delivery, per-run limits and authenticated readers. Preserve final result stdout/stderr independently. Keep endpoint handlers and adapters in Python; scheduling and admission remain native.
- Freeze helper files in module generation snapshots. Keep device credentials, image binaries, backups and actual run evidence under ignored local state. Use prepared offline wheels and native builds for board bootstrap.

## Risks / Trade-offs

- [Missing KVM permissions or QEMU runtime] Report unmet prerequisites and never silently classify emulation as hardware acceleration.
- [Guest fails to respond or stop] Terminate only the managed instance; retain uncertain evidence and quarantine when cleanup cannot be confirmed.
- [Large image transfer] Stream to private staging files, bound expanded sizes and validate before publication.
- [Excess experiment output] Bound capture and API storage, report truncation, and never block experiment cleanup on readers.
- [Local path or credential publication] Keep private state ignored, scan staged changes, and publish only generic configuration examples.

## Migration Plan

Apply additive SQLite migrations and preserve legacy immediate submissions and final result formats. Upgrade the agent with the controller for streaming and environment support. Existing Linux and libvirt profiles remain selectable. Environment preparation and runtime installation happen centrally or administratively; board execution consumes only supplied local packages.
