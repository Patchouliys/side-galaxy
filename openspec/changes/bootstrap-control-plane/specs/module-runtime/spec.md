# Module runtime

## Purpose

Connect Raspberry Pi 4, Raspberry Pi 5, and future boards through explicit profiles and an execution protocol. Allow developers to update management modules between experiments while preserving the module version and result consistency of running jobs.

## ADDED Requirements

### Requirement: Capability discovery

The agent SHALL offer Pi 4, Pi 5, and generic board profiles and discover actual CPUs, available memory, and execution capabilities. It SHALL NOT describe process affinity as hypervisor isolation or hardware cache partitioning.

#### Scenario: Unsupported QoS
- **WHEN** the Linux process module receives a request for hardware bandwidth isolation
- **THEN** it rejects the request and reports that the capability is unsupported

### Requirement: Hot reload

The agent SHALL pin each job's module generation by content digest and probe updates before accepting them. New generations SHALL apply only to subsequent jobs. Failed updates SHALL retain the previous generation and report an error.

#### Scenario: Reload during execution
- **WHEN** a module is updated while a job is running
- **THEN** the current job uses its original snapshot and subsequent jobs use the validated new snapshot

### Requirement: Bounded execution

Execution modules SHALL run in independent processes with time limits. Cancellation and timeout SHALL clean up their process groups. Network requests SHALL NOT accept arbitrary shell commands, module source, or module paths.

#### Scenario: Cancel a workload
- **WHEN** an operator cancels a running job
- **THEN** the agent terminates the experiment process groups and reports a terminal state

### Requirement: KVM live experiment

The KVM module SHALL operate only on a locally configured, running libvirt domain, save, apply, and restore live vCPU affinity, collect domain statistics, and record restoration results. Restoration failure SHALL fail the job and quarantine the board.

#### Scenario: Finish KVM experiment
- **WHEN** a KVM affinity experiment finishes or receives a cancellation it can handle
- **THEN** it restores the original vCPU affinity and records the domain UUID and restoration status without rebooting the board

### Requirement: Transfer and execute workloads

The agent SHALL download artifacts and verify their digests. The Linux module SHALL execute the experiment declared by the bundle. The KVM module SHALL transfer the bundle and a pinned runner into the configured VM through the guest agent, execute the experiment, and collect exit status, logs, and output files. The simulator SHALL report simulated delivery only and SHALL NOT claim to have executed uploaded code.

#### Scenario: KVM guest execution
- **WHEN** the configured running VM provides QEMU Guest Agent and Python 3
- **THEN** the module transfers the experiment into that job's guest workspace, executes it, collects results, and restores live affinity

#### Scenario: Missing guest transport
- **WHEN** the guest agent is unavailable
- **THEN** the module does not advertise workload support and preflight rejects that template
