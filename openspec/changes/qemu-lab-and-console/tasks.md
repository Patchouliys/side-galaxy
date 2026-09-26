# Tasks

## 1. Local QEMU target

- [x] 1.1 Implement verified-image QEMU lifecycle, private seed/SSH state, guest provisioning and registration; cover command construction, privacy and stop identity with automated checks.
- [x] 1.2 Add CLI defaults and local image/source overrides, document the runnable lab workflow, and boot an actual ARM64 Linux guest to a ready board state.

## 2. Portable experiments

- [x] 2.1 Validate optional environment requirements, discover actual Linux/KVM execution environments, and enforce requirements in C++ admission and the runner; test mismatches, missing discovery and unchanged legacy bundles.
- [x] 2.2 Add replay through shared HTTP/CLI/MCP operations and console plan reuse; verify immutable artifact preservation, new targets, idempotency and unchanged source history.
- [x] 2.3 Add a C compilation example and environment-contract documentation; run it inside QEMU and retrieve its actual output.

## 3. Console workflow

- [x] 3.1 Reorganize inventory, configuration and history with persistent selections, filters, device details and per-target preflight feedback; verify desktop and narrow layouts in the browser.
- [x] 3.2 Improve task states, elapsed time, log/output inspection and selected-target replay; verify artifact upload through the API and the selection-to-result console workflow using a real guest target.

## 4. Integration and publication

- [x] 4.1 Run native and Python regression tests, protocol integration, package checks and strict OpenSpec validation; publish the completed source and bilingual entry documentation using the repository owner's identity.
