# Proposal

## Why

Developers without physical boards need a local Linux target that really compiles and executes their experiment code. The console currently hides available device details, loses selections during refresh, and makes it difficult to diagnose preflight failures or reuse an experiment on another target.

## What Changes

- Add a managed QEMU Linux lab with verified cloud images, private overlays, guest provisioning, agent registration, status, and stop operations.
- Run the existing Linux execution module inside the guest so uploaded bundles, native compilation, logs, and outputs use the same protocol as physical Linux agents.
- Declare experiment environment requirements and check them against discovered target capabilities before admission and execution.
- Reuse an experiment's immutable artifact and parameters on selected replacement boards after a fresh preflight.
- Reorganize the console into device inventory, experiment setup, and history with detailed device inspection, persistent selection, filters, per-target errors, and accessible results.

## Capabilities

### New Capabilities

- `local-qemu-lab`: Real Linux virtual targets with repeatable local lifecycle and guest provisioning.
- `experiment-portability`: Environment contracts and controlled reuse of an experiment on different targets.
- `console-workflow`: Discoverable device information and a coherent experiment configuration, inspection, and reuse workflow.

### Modified Capabilities

None. Existing bootstrap capabilities remain preserved.

## Impact

Adds QEMU and SSH as local lab tools while retaining the C++ scheduling core and existing HTTP, CLI, MCP, artifact, and agent protocols. Extends environment discovery, artifact validation, native admission, and frontend rendering. Local VM disks, credentials, connection details, and logs remain outside Git. ARM64 Linux user-space compatibility is the initial target; emulated board peripherals and performance equivalence are separate concerns.
