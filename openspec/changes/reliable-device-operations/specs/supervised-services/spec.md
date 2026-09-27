# Spec Delta

## Purpose

Provide reliable supervised services for real embedded experiment devices and their operators.

## ADDED Requirements

### Requirement: Persistent controller and transport
The local CLI SHALL install and inspect operating-system supervised controller and optional SSH tunnel services using private configuration. Unexpected exit SHALL trigger manager-controlled restart without launching duplicate managed instances.

#### Scenario: Tunnel interruption
- **WHEN** a configured tunnel exits after a USB disconnect
- **THEN** its service manager retries and restores forwarding when the connection returns

### Requirement: Health and privacy
Service diagnostics SHALL distinguish installed, running and reachable states without disclosing private configuration. Network APIs SHALL NOT expose arbitrary service definitions or host shell execution.

#### Scenario: Controller process without API readiness
- **WHEN** the supervisor reports a process but its health endpoint is unreachable
- **THEN** status reports the readiness failure separately
