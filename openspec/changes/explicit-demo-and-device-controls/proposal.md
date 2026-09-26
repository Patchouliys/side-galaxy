# Proposal

## Why

The console currently mixes synthetic samples with real experiments, while recovery operations wait for an idle device. Operators need explicit demo controls and decisive reload/restart actions during experiments.

## What Changes

- Start a real, loopback-only workspace without sample devices by default; separate local access from demo generation.
- Provide an operator-only demo switch that starts/stops sample agents and filters synthetic inventory/history without deleting records.
- Add forced module reload with atomic admission blocking, cancellation, cleanup evidence, and a visible acknowledgement.
- Add identity-checked soft or forced restart of locally managed QEMU guests, preserving disks and board identity.
- Improve console hierarchy with restrained galaxy styling, concise controls, clear destructive-action confirmation, and reduced-motion support.

## Capabilities

### New Capabilities

- `workspace-modes`: Explicit demo activation, local access boundaries, and synthetic-data visibility.
- `device-lifecycle`: Forced reload and managed QEMU restart with resource-state protection.
- `console-visual-controls`: Clear lifecycle actions and restrained visual enhancements.

### Modified Capabilities

None. Existing behavior is described in prior unarchived changes.

## Impact

C++ admission/state, agent runtime, HTTP/CLI/MCP, local QEMU orchestration, console assets, tests, and bilingual entry documentation. No new frontend dependencies or arbitrary host command endpoints.
