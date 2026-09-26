# Console workflow

## Purpose

Make board state, experiment configuration, preflight feedback, and execution results easy to inspect and operate from one coherent console.

## ADDED Requirements

### Requirement: Inspect and select devices
The console SHALL support inventory search and status filtering, show available resources and active work, and expose full device capabilities and module state. Refresh SHALL preserve the user's selected devices while visibly marking unavailable targets.

#### Scenario: A selected device becomes busy
- **WHEN** polling reports that a selected target is busy or offline
- **THEN** the selection remains visible and subsequent preflight explains why it cannot execute

### Requirement: Configure and diagnose experiments
The console SHALL separate device discovery, experiment configuration, and history without hiding the selected target summary. Artifact information, resource parameters, and per-target preflight errors SHALL be available before submission.

#### Scenario: Fix an invalid resource plan
- **WHEN** preflight rejects selected targets
- **THEN** the console presents each target's reasons alongside the editable experiment configuration

### Requirement: Inspect and reuse results
The console SHALL filter experiment history, display actual per-target states and elapsed time, and provide accessible logs, outputs, and plan reuse. Progress SHALL reflect observed state rather than invented live measurements.

#### Scenario: Inspect and rerun a completed batch
- **WHEN** an operator opens a completed batch
- **THEN** logs and output downloads are available and its plan can be copied to the currently selected targets for a fresh preflight
