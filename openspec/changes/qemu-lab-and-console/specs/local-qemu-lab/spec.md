# Local QEMU lab

## Purpose

Provide a real Linux execution target that developers can provision and use locally before connecting physical boards.

## ADDED Requirements

### Requirement: Managed local guest
The platform SHALL provide repeatable commands to start, inspect, and stop a QEMU Linux guest using a verified base image and a private writable overlay. Starting an existing lab SHALL preserve its disk and identity. Local credentials and machine paths SHALL remain outside version control.

#### Scenario: Create a local ARM64 target
- **WHEN** a developer starts a lab with the required QEMU tools and a verified ARM64 Linux image
- **THEN** the guest boots with local-only management access, installs the agent, and appears in the shared board inventory

#### Scenario: Stop without unrelated process termination
- **WHEN** a developer stops the managed lab
- **THEN** only its VM and managed connection are stopped while its reusable disk is retained

### Requirement: Actual guest execution
A lab target SHALL execute uploaded bundles with the same Linux runtime protocol as a physical Linux target. Results SHALL identify the guest execution environment and preserve artifact hashes, logs, output files, and cleanup state. Lab results SHALL NOT be described as measurements from physical Raspberry Pi hardware.

#### Scenario: Compile and execute a C experiment
- **WHEN** a compatible bundle containing C source and a compiler setup command is submitted to the guest
- **THEN** it compiles and executes inside Linux and returns its actual process result and declared output
