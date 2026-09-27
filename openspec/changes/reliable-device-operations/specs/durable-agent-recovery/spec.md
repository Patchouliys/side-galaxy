# Spec Delta

## Purpose

Provide reliable durable agent recovery for real embedded experiment devices and their operators.

## ADDED Requirements

### Requirement: Durable completion delivery
The agent SHALL persist claims before execution and terminal completion before transmission, and SHALL retry an unacknowledged completion after restart without re-executing its experiment.

#### Scenario: Restart after delivery failure
- **WHEN** an agent restarts with a saved completion
- **THEN** it resends the same completion and starts no duplicate workload

### Requirement: Conservative reconciliation
The agent SHALL use boot and process identity before signaling surviving processes and SHALL retain uncertainty for resources it cannot verify. A second local agent for the same target SHALL fail before polling.

#### Scenario: Unknown external resources
- **WHEN** an agent restarts during a KVM workload without saved completion
- **THEN** the run remains unsafe for automatic resource reuse and is not relaunched
