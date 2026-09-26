# Operator interfaces

## Purpose

Present boards and experiments through a consistent Side Galaxy visual identity. Expose the same preflight, submission, query, cancellation, and module-reload operations to people and AI clients, reducing manual work in batch management and experiment reproduction.

## ADDED Requirements

### Requirement: Shared experiment workflow

Web, CLI, and MCP SHALL use the same control plane for multi-board preflight, submission, queries, and cancellation. MCP write operations SHALL require explicit enablement.

#### Scenario: AI read only
- **WHEN** MCP starts with its default configuration
- **THEN** AI clients can query and preflight but cannot start or cancel jobs

### Requirement: Galaxy identity

The Web interface SHALL use a vector identity based on a galaxy viewed from the side, a deep-space background, and clear status indicators. It SHALL support keyboard operation and small screens and explicitly identify demo mode.

#### Scenario: Simulation dashboard
- **WHEN** the local demo is opened
- **THEN** the interface shows simulated boards and explicitly states that synthetic metrics are not physical measurements

### Requirement: Deployment entry

The project SHALL provide inventory examples for multiple devices and repeatable server and agent deployment entry points. Secrets SHALL come from environment variables or private local configuration.

#### Scenario: Public repository
- **WHEN** version-controlled deployment files are inspected
- **THEN** they contain only fictitious addresses and placeholder configuration, without real identities or secrets

### Requirement: Experiment artifacts

The platform SHALL accept ZIP bundles containing `experiment.json` and experiment code, store versions by SHA-256, and let Web, CLI, and MCP clients select artifacts and supply additional arguments and environment variables for multi-board submission. Bundles SHALL declare `setup` and `run` commands and output paths rather than being limited to built-in templates.

#### Scenario: Upload and run custom code
- **WHEN** an operator uploads a valid experiment bundle and selects boards that support workload execution
- **THEN** the platform validates the bundle, computes its digest, permits preflight and submission, and provides final logs and output-file downloads

### Requirement: Artifact validation

The platform SHALL limit compressed and expanded bundle sizes and reject path traversal, symbolic links, duplicate members, and invalid manifests. Artifact downloads SHALL require authorization as an operator or the assigned board agent.

#### Scenario: Unsafe archive paths
- **WHEN** an uploaded ZIP contains absolute paths or parent-directory traversal
- **THEN** the platform rejects it without registering an artifact

