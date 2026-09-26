# Spec Delta

## Purpose

Separate synthetic demonstrations from real laboratory operation without losing experiment records.

## ADDED Requirements

### Requirement: Real workspace by default
The server SHALL start without generating synthetic devices unless demo mode is explicitly selected. Local unauthenticated access SHALL be restricted to loopback independently of demo mode.

#### Scenario: Normal local start
- **WHEN** an operator starts the default loopback server
- **THEN** real enrolled devices are visible and synthetic devices are hidden without requiring demo mode for local access

### Requirement: Operator demo switch
The operator SHALL be able to enable and disable demo mode through the console and shared API. Disabling SHALL stop sample workers, cancel synthetic work, prohibit new synthetic admission, and hide synthetic inventory and synthetic-only history without deleting it or affecting real work.

#### Scenario: Toggle off with existing data
- **WHEN** demo mode is disabled with sample data and a real QEMU target present
- **THEN** the QEMU target remains available, samples disappear, and old sample identifiers cannot bypass admission

#### Scenario: Read-only caller
- **WHEN** a read-only caller attempts to change workspace mode
- **THEN** the request is rejected
