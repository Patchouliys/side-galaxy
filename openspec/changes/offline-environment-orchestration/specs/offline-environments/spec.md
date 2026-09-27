## Purpose

Deliver complete prepared experiment guests to offline boards and reset each run without restarting the physical host.

## ADDED Requirements

### Requirement: Verified offline environment packages
The platform SHALL accept bounded prepared guest packages identified by content digest, validate declared files and architecture, and transfer them only to authorized execution targets. Execution SHALL not require board Internet access.

#### Scenario: Offline guest deployment
- **WHEN** a compatible target receives a valid environment package and experiment bundle
- **THEN** it boots the prepared environment and executes the supplied workload using only transferred and preinstalled dependencies

#### Scenario: Invalid image package
- **WHEN** an archive contains unsafe paths, links, oversized data or mismatched digests
- **THEN** publication and execution are rejected

### Requirement: Isolated writable state and evidenced cleanup
Each VM experiment SHALL use an immutable base plus independent writable state. Cancellation SHALL stop only its managed instance, and reset SHALL discard writable state only after termination is confirmed. Results SHALL identify the accelerator and environment digest; emulation MUST NOT be represented as KVM execution.

#### Scenario: Repeat from a clean environment
- **WHEN** a completed environment experiment is run again
- **THEN** the new guest uses a fresh writable layer and previous writes do not modify the base image

#### Scenario: Cleanup cannot be confirmed
- **WHEN** managed instance termination is uncertain
- **THEN** the target remains unavailable for new work and retains cleanup evidence
