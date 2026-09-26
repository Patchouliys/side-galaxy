# Tasks

## 1. Research and Workflow

- [x] 1.1 Deliver research from official sources and a phased roadmap, verify Pi, KVM, and shared-resource boundaries, and pass strict OpenSpec validation.
- [x] 1.2 Pin the OpenSpec and Ponytail skill sources, dependencies, and licenses, and verify successful dependency installation.

## 2. Control Plane

- [x] 2.1 Implement resource preflight, atomic batch submission, idempotency, leases, authentication, and quarantine after agent loss; verify critical failure paths with automated tests.
- [x] 2.2 Implement persisted results, simulated execution, and the independent agent protocol; validate the complete simulated batch lifecycle and document API usage.

## 3. Module Runtime

- [x] 3.1 Implement Pi board profiles and content-addressed module discovery and hot reload; test successful updates, failed-update rollback, and generation pinning, and document module development.
- [x] 3.2 Implement the Linux process module and KVM live affinity, statistics, and restoration module; run protocol checks and fake-virsh recovery tests.

## 4. Interfaces and Deployment

- [x] 4.1 Implement SVG branding and a responsive Web interface; verify multi-board selection, submission, queries, cancellation, and module reload in the browser.
- [x] 4.2 Implement CLI and MCP access through the shared API; verify CLI JSON, MCP initialization, queries, read-only restrictions, and the write workflow.
- [x] 4.3 Provide container and Ansible deployment for multiple boards with operating documentation; complete build and configuration checks.

## 5. Integration and Publication

- [x] 5.1 Complete integration tests, privacy scanning, usage documentation.
- [x] 5.2 Create and push a public GitHub repository using the repository owner's GitHub identity; verify remote visibility and commit metadata.

## 6. Experiment Bundle Workflow

- [x] 6.1 Implement ZIP manifest validation, a content-addressed artifact store, and authenticated upload and download; test traversal, duplicate members, tampering, and admission failures.
- [x] 6.2 Implement a pinned runner, Linux delivery and execution, and KVM guest file, execution, and cancellation protocols; test a real sample program and simulated QGA transport.
- [x] 6.3 Add artifact and custom experiment entry points, logs, and output downloads to Web, CLI, and MCP; validate local upload through an independent agent.

## 7. Product Landing Page

- [x] 7.1 Add a separate landing page, an animated side-view galaxy, and reduced-motion support; verify the landing page and console entry point in the browser.
- [x] 7.2 Add a layered galactic core, animated dust disk, and light trails; verify the browser rendering, reduced-motion preference, and animation suspension in the background.
