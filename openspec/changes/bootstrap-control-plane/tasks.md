# Tasks

## 1. Research and Workflow

- [x] 1.1 Deliver research from official sources and a phased roadmap, verify Pi / KVM / shared-resource boundaries, and pass strict OpenSpec validation.
- [x] 1.2 Pin the OpenSpec and Ponytail skill sources, dependencies, and licenses, and successfully install dependencies.

## 2. Control Plane

- [x] 2.1 Implement resource preflight, atomic batch submission, idempotency, leases, authentication, and quarantine after agent loss; test critical failure paths automatically.
- [x] 2.2 Implement persisted results, simulated execution, and the independent agent protocol; validate the complete simulated batch lifecycle and document API usage.

## 3. Module Runtime

- [x] 3.1 Implement Pi profiles and content-addressed module discovery/hot reload; test valid updates, failed-update rollback, and generation pinning, and document module development.
- [x] 3.2 Implement the Linux process module and KVM live affinity/statistics/restoration module; run protocol checks and fake-virsh recovery tests, listing physical-target acceptance as not executed.

## 4. Interfaces and Deployment

- [x] 4.1 Implement SVG branding and responsive Web interfaces; verify multi-board selection, submission, queries, cancellation, and module reload in the browser.
- [x] 4.2 Implement CLI/MCP access through a shared API; verify CLI JSON, MCP initialization, queries, read-only restrictions, and the write workflow.
- [x] 4.3 Provide container and Ansible deployment for multiple boards and operating documentation; complete build and configuration static checks, identifying actual board deployment separately.

## 5. Integration and Publication

- [x] 5.1 Complete integration tests, privacy scanning, usage instructions, and records of physical-target acceptance boundaries.
- [x] 5.2 Create and push a public GitHub repository using a generic project commit identity; verify remote visibility and commit metadata.

## 6. Real Experiment Bundle Workflow

- [x] 6.1 Implement ZIP manifest validation, a content-addressed artifact store, and authenticated upload/download; test traversal, duplicate members, tampering, and admission failure.
- [x] 6.2 Implement a pinned runner, Linux delivery/execution, and KVM guest file/execution/cancellation protocols; test a real example program and simulated QGA transport.
- [x] 6.3 Add artifacts, custom experiments, logs, and output downloads to Web/CLI/MCP; validate the local upload-to-independent-agent integration and record physical-target boundaries.

## 7. Product Landing Page

- [x] 7.1 Add a separate landing page, animated side-view galaxy, and reduced-motion support; verify the landing page and console entry point in the browser.

- [x] 7.2 Following landing-page feedback, upgrade the galaxy with a layered core, animated dust disk, and light trails; verify browser rendering, reduced-motion preferences, and background suspension.
