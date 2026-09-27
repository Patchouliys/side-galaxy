# Spec Delta

## Purpose

Provide reliable physical resource admission for real embedded experiment devices and their operators.

## ADDED Requirements

### Requirement: Physical-host atomic admission
The native scheduler SHALL admit at most one experiment per identified physical host, reject a batch containing duplicate physical hosts, and preserve fair ordering for overlapping hosts. Unknown legacy identities SHALL be explicit.

#### Scenario: Different modules on one board
- **WHEN** a target is running and a sibling target on the same host receives an experiment
- **THEN** the new experiment waits or is rejected without acquiring conflicting resources

### Requirement: Host-wide uncertainty gates
Quarantine, reload and maintenance SHALL prevent sibling admission. Host identity changes SHALL NOT bypass an existing lease or uncertain cleanup. Recovery SHALL NOT silently clear unrelated sibling quarantine.

#### Scenario: Identity changes while occupied
- **WHEN** an agent attempts to change its host binding while its previous host is occupied
- **THEN** the change is rejected and the original resource protection remains

### Requirement: Process-tree resource limits
Delegated targets SHALL support aggregate experiment memory limits and selected CPU placement, accounting separately for VM host overhead. Explicit cgroup enforcement requests SHALL fail if unavailable. Cleanup evidence SHALL include resource-scope emptiness.

#### Scenario: Unavailable delegation
- **WHEN** an operator requests cgroup enforcement on a target lacking delegation
- **THEN** preflight rejects the request instead of claiming that process-tree limits are enforced
