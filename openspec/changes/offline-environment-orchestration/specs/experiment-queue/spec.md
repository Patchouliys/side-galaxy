## Purpose

Provide persistent experiment waiting queues without weakening atomic resource admission or cleanup safety.

## ADDED Requirements

### Requirement: Atomic fair queued admission
The system SHALL support opt-in queued submission, keep waiting requests without active resource leases, and atomically admit a whole batch only after all targets pass dispatch-time checks. Overlapping requests SHALL preserve FIFO order while independent targets can progress.

#### Scenario: Occupied target becomes available
- **WHEN** an eligible queued batch waits for a running experiment to finish cleanly
- **THEN** it receives every required lease atomically and pins the current module generations before execution

#### Scenario: Independent target is ready
- **WHEN** an earlier batch is waiting on an unrelated target
- **THEN** a later batch targeting only free independent devices can proceed

### Requirement: Durable cancellation and evidence
The system SHALL preserve queued intent across restart, reject conflicting idempotency-key reuse, cancel waiting work without execution, and retain uncertain cleanup quarantine and late completion evidence.

#### Scenario: Cancel before admission
- **WHEN** a waiting batch is cancelled
- **THEN** no agent executes it and it consumes no target resources

#### Scenario: Late completion after loss
- **WHEN** an authenticated agent reports completion for a lost run with the pinned generation
- **THEN** the evidence is retained while the lost state and quarantine remain until explicit recovery
