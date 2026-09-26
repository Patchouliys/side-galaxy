# Design

## Context

The C++20 core owns admission and state transitions. Python exposes HTTP, CLI, MCP, artifact storage, and trusted execution modules. Existing synthetic targets validate orchestration but do not run uploaded code. The local development host is ARM64 macOS; physical targets use Linux and initially include Pi 4 and Pi 5. See proposal.md for motivation.

## Goals / Non-Goals

**Goals:** Boot a reusable Linux guest, compile and execute ordinary experiment bundles, discover execution-environment compatibility, and reuse immutable plans on replacement targets. Preserve the native scheduling boundary and existing databases.

**Non-Goals:** Raspberry Pi peripheral emulation, guest live migration, copying an entire VM onto a board, nested KVM on every host, or automatic performance equivalence. Physical deployment continues to use the existing Linux agent and Ansible workflow.

## Decisions

- Use QEMU ARM `virt` with a Debian ARM64 cloud image, a verified base digest, a qcow2 overlay, and NoCloud seed. Prefer HVF on matching macOS hardware or KVM on Linux; retain TCG for software emulation. Standard QEMU is portable and avoids another VM management service.
- Implement local lifecycle orchestration around QEMU, SSH, QMP, and the existing agent. SSH management binds to loopback. A private SSH master reverse-forwards the guest's controller endpoint so the existing loopback demo can serve real guest agents without opening a host network listener. Verify VM identity through QMP before stopping it; retain reusable disks.
- Build the platform's source distribution inside the guest with the guest's native compiler. Keep image identity, settings, private keys, and bootstrap logs in ignored local state. Do not copy the developer checkout wholesale or upload machine paths to the server.
- Add an optional manifest `requires` object with CPU architecture choices, an OS identifier, and executable names. Add a bounded `execution_environment` description from the actual runtime (guest for KVM). Pass verified artifact requirements into C++ admission; unknown or incompatible requested environments fail closed. Repeat checks in the runner before setup. Bundles without requirements retain their existing behavior.
- Implement replay by reading the source batch plan, replacing target board IDs, validating through the existing Plan model and native submit path, and requiring a new idempotency key. Reuse the immutable artifact, arguments, and environment; preserve source history.
- Keep the frontend framework-free. Separate inventory, experiment configuration, and history; maintain selected targets across refresh; use the existing API's resource, heartbeat, module, run, log, and output data. Explain per-target admission failures near the editable plan. Show completed target counts and elapsed time rather than fabricated live telemetry.

## Risks / Trade-offs

- [Guest image or dependency download failure] Verify digests, retain resumable local inputs, provide actionable errors, and support explicit local images/source archives.
- [Architecture or userspace mismatch] Detect declared requirements before admission; compile inside the selected Linux environment and capture actual failures as results.
- [Host-only features leaking into guest discovery] Probe KVM requirements inside the guest and avoid publishing local executable paths.
- [VM shutdown during active work] Keep controller cancellation/quarantine semantics intact and make explicit lab stop local to that lab identity.
- [Excess information in the console] Keep summaries in tables and put detailed capabilities, raw results, and logs in focused inspection views.

## Migration Plan

Existing experiment bundles and board descriptions remain accepted when no environment requirements are declared. Install the updated agent to publish environment details. Start a local lab, execute a portable bundle, then register physical Linux boards through the existing deployment workflow and replay the same artifact after a fresh compatibility check.
