## Purpose

Let operators inspect actual experiment output while work runs without unbounded storage or loss of final results.

## ADDED Requirements

### Requirement: Authenticated incremental output
The system SHALL expose ordered stdout, stderr and supported environment output events through authenticated APIs, CLI, MCP and the console while execution is active. Repeated delivery SHALL be idempotent and readers SHALL resume from a sequence cursor.

#### Scenario: Observe a running workload
- **WHEN** an active workload emits output and the reader polls with its last cursor
- **THEN** only subsequent retained events are displayed without waiting for final completion

### Requirement: Bounded capture and truthful states
Log transport SHALL have explicit size limits, report truncation, preserve final completion independently, and reject writes from agents that do not own the run.

#### Scenario: Excess output
- **WHEN** output exceeds the retained log budget
- **THEN** storage remains bounded and the reader sees a truncation indication while execution and cleanup continue

#### Scenario: Unauthorized log write
- **WHEN** a different target attempts to append events for a run
- **THEN** the server rejects the write
