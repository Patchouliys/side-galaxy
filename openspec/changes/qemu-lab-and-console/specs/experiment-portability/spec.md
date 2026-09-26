# Experiment portability

## Purpose

Reuse immutable experiments across virtual and physical Linux targets while detecting declared environment incompatibilities before execution.

## ADDED Requirements

### Requirement: Declared environment requirements
Experiment bundles SHALL optionally declare supported CPU architectures, operating system, and required executable names. The platform SHALL validate the declaration, expose it in artifact metadata, and reject admission when a target lacks a required or known-compatible execution environment. Existing bundles without this declaration SHALL remain valid.

#### Scenario: Incompatible destination
- **WHEN** an ARM64-only experiment is preflighted or submitted to an x86_64 target
- **THEN** the request identifies the architecture mismatch and starts no experiment

#### Scenario: Requirements no longer hold
- **WHEN** an admitted target no longer provides a required command at execution time
- **THEN** execution fails explicitly before running setup or experiment commands

### Requirement: Reuse on replacement boards
Web, CLI, and MCP SHALL allow an operator to reuse an existing batch plan on selected replacement boards while retaining the original artifact digest and experiment parameters. Submission SHALL perform fresh atomic admission and use a new caller-supplied idempotency key. Reuse SHALL NOT alter the source batch.

#### Scenario: Promote a local experiment
- **WHEN** an operator selects a completed local experiment and compatible physical targets
- **THEN** the new batch uses the same immutable experiment artifact, records the new target runs, and retains the original result
