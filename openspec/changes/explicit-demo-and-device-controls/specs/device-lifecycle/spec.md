# Spec Delta

## Purpose

Let operators interrupt laboratory work and restore device execution through explicit lifecycle controls.

## ADDED Requirements

### Requirement: Forced module reload
The system SHALL provide a force reload action that cancels current execution and stages, blocks new admission during reload, validates the replacement, and acknowledges completion. Unverified cleanup SHALL keep the device quarantined.

#### Scenario: Reload during an experiment
- **WHEN** an operator requests force reload on a busy board
- **THEN** its task is interrupted and new work is rejected until cleanup and module reload are acknowledged

#### Scenario: Invalid replacement
- **WHEN** replacement validation fails
- **THEN** the error is reported and the previous valid module remains available without claiming the replacement succeeded

### Requirement: Managed QEMU restart
The system SHALL restart only operator-configured local QEMU instances after verifying instance identity. Soft restart and forced reset SHALL preserve disks and board identity, protect admission, and require a changed guest boot identity before declaring restart complete.

#### Scenario: Forced reset with active work
- **WHEN** the operator confirms a forced reset of a managed QEMU target
- **THEN** old execution is recorded as interrupted, restart blocks new work, and completion requires a fresh guest boot and restored agent connection

#### Scenario: Failed or wrong instance
- **WHEN** VM identity does not match or restart times out
- **THEN** the operation fails without resetting another instance or reporting the board ready
