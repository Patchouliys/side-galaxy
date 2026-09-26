# Fleet control

## Purpose

Provide shared availability reporting, capability checks, job submission, status queries, and result traceability for experiments across boards. Operators and AI clients follow the same resource-management rules, with simulated results clearly distinguished from physical measurements.

## ADDED Requirements

### Requirement: Atomic admission

The system SHALL check every target's availability, resource ranges, reserved CPUs, capabilities, and occupancy within one transaction. Any failure SHALL prevent creation of a partial batch. The same idempotency key and request SHALL return the same batch; reusing the key for a different request SHALL be rejected.

#### Scenario: Conflicting board
- **WHEN** a batch includes an occupied or offline board
- **THEN** the system reports the reason and creates no jobs for any target

### Requirement: Safe lifecycle

The system SHALL persist job states and quarantine a board after its executing agent is lost or its execution deadline expires. Cancelling a running job SHALL wait for agent confirmation before releasing resources. Jobs with unknown execution state SHALL NOT be automatically executed again.

#### Scenario: Agent disappears
- **WHEN** the heartbeat of an agent with a running job expires
- **THEN** the job is marked lost and the board rejects new jobs until explicit recovery

### Requirement: Scoped access

The system SHALL distinguish operator tokens, read-only tokens, and individual board-agent tokens. Token-free operation SHALL be limited to explicitly enabled local demo mode.

#### Scenario: Wrong agent
- **WHEN** an agent attempts to read another board's job
- **THEN** access is denied

### Requirement: Reproducible evidence

The system SHALL retain request digests, module digests, timestamps, execution modes, and results. Simulated results SHALL be marked synthetic. Physical experiments SHALL retain board boot IDs from before and after execution for comparison.

#### Scenario: Export a run
- **WHEN** a completed job is exported
- **THEN** the result is structured JSON containing its execution mode and resource plan
