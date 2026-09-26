# Design

## Context

C++ owns atomic admission and persistent task transitions. Agents already cancel workloads and validate module snapshots at idle boundaries. QEMU has a private state directory, QMP UUID checks, and a loopback SSH tunnel. See proposal.md for motivation.

## Goals / Non-Goals

**Goals:** Real operation by default; explicit runtime demo mode; force reload across agent-backed targets; restart managed local QEMU with visible operation state.

**Non-Goals:** Arbitrary shell commands, remote host reboot without a management adapter, restarting the controller host, deleting sample history, and cosmetic performance charts.

## Decisions

- Separate local loopback access from sample generation instead of using demo mode to bypass authentication. Default CLI serve on loopback supports local access; remote listeners require a token.
- Keep demo mode and synthetic admission policy in the native core. The HTTP layer starts/stops local sample workers and filters synthetic-only inventory/history. This prevents a hidden sample from accepting new work through another interface.
- Reuse cancellation plus module validation for force reload. Native reload generation blocks admission until acknowledged, preventing starvation and stale module execution.
- Register managed lab directories at server launch, never from a browser-provided filesystem path. Map public instance IDs to private paths server-side. Restart uses existing SSH/QMP with UUID verification and checks a changed guest boot ID; protect scheduling with native maintenance state.
- Retain framework-free console code. Add compact lifecycle controls, explicit confirmations, cyan/violet accents, and motion behind content with reduced-motion fallbacks.

## Risks / Trade-offs

- [Forced reset interrupts output writes] Explain interruption at the action and preserve run provenance; never label it successful experiment execution.
- [Reconnect fails after reset] Retain maintenance/quarantine and report failure; do not release scheduling on a timer alone.
- [Demo changes race with submission] Native transactions enforce mode and cancellation while sample-agent lifecycle is serialized.
- [Authentication confused with demo] Fixed startup access policy cannot be changed by the demo switch.

## Migration Plan

Preserve existing board IDs, databases, artifacts, and history. Upgrade native state tables additively. Start the existing local server without demo generation, reconnect its QEMU agent, and retain explicit demo activation for sample workflows.
