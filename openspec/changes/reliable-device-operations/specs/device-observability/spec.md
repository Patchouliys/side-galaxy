# Spec Delta

## Purpose

Provide reliable device observability for real embedded experiment devices and their operators.

## ADDED Requirements

### Requirement: Measured bounded history
The system SHALL collect actual CPU utilization and frequency, available temperature, memory and disk measurements with bounded retention. Missing sensors SHALL remain unavailable and freshness SHALL use controller receipt time.

#### Scenario: Missing or stale sample
- **WHEN** a device has no supported temperature sensor or has stopped reporting
- **THEN** the monitor labels that value unavailable or stale without fabricating zero

### Requirement: Shared monitoring interfaces
The system SHALL expose reader-authorized telemetry and physical-host allocations through Web, CLI and MCP, including current experiment occupancy and resource enforcement availability.

#### Scenario: Related execution targets
- **WHEN** two targets report the same physical host identity
- **THEN** their monitoring views show their shared host and all current host allocations
