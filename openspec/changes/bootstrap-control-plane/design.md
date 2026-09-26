# Design

## Context

The repository is empty. Pi 4 and Pi 5, a public GitHub repository, and management-module hot reload are confirmed. Linux with KVM is the selected hypervisor environment, but board addresses, OS versions, and VM names are unavailable. See proposal.md.

## Goals / Non-Goals

Goals: A complete control-plane workflow that can be validated locally; independent agents and a module protocol; deployable source; a real Linux process experiment module awaiting board acceptance.
Non-Goals: This iteration does not claim physical KVM acceptance, Jailhouse control, hard real-time behavior, MPAM, cache isolation, synchronized multi-device barriers, or production readiness.

## Decisions

- Use Python, FastAPI, Pydantic, SQLite, and native HTML/CSS/JS. This simplifies deployment on one server and local development compared with separate microservices and a frontend build. Use the maintained v1 API of the official Python MCP SDK, pinned below v2, rather than implementing the protocol manually.
- The server orchestrates; agents poll outbound with individual board tokens. Web, CLI, and MCP use operator/read tokens. A reverse proxy or SSH tunnel supplies TLS or protected transport; local demo mode is explicitly enabled. The interface stores tokens only in memory.
- Grant one task lease per board; each experiment may contain a victim and interferer. Use SQLite BEGIN IMMEDIATE for atomic batch admission. Add resource-graph scheduling when multiple simultaneous experiments on one board are required.
- Requests contain boards, templates, victim/interference CPU sets, memory, and duration. Run preflight before submission and repeat validation during submission. Report unsupported capabilities, offline or quarantined boards, and conflicts as explicit errors.
- Track queued, running, cancelling, succeeded, failed, cancelled, and lost states. Cancellation cannot release resources before agent confirmation. Quarantine lost boards and require explicit recovery after workload termination is confirmed. Do not claim distributed exactly-once execution.
- SQLite stores plans and their SHA-256, module digests, and results. Demo mode can run simulators inside the server; independent agents support simulator and Linux process experiment modules.
- Store board descriptions as data. Modules are trusted standalone Python files deployed by administrators and use a stdin/stdout JSON protocol. Copy source into private snapshots named by SHA-256 before discovery and execution. Start each task in a new process group. Remote APIs cannot upload management-module source or specify host-local paths. Hot reload occurs at idle polling boundaries; existing processes retain their snapshots, and failure preserves the previous generation. Subprocesses provide fault containment, not a security sandbox for malicious plugins.
- The Linux module only provides process affinity, address-space limits, and bounded microbenchmarks. CPU 0 is reserved for management by default. Other host processes may still use the same CPUs; this does not replace a hypervisor, cgroups, or resctrl.
- Draw the side-view galaxy identity as an original SVG: a horizontal elliptical disk, tilted orbit, and bright core, using deep navy, cyan, and warm white. Avoid external fonts and tracking resources.

## Risks / Trade-offs

- [Missing hardware information] Provide capability discovery and a complete simulated workflow; validate physical targets separately.
- [Malicious or uncontrolled plugins] Restrict module deployment to trusted administrators and terminate process groups on timeout. Use narrowly scoped helpers for future privileged operations.
- [Uncontrolled shared-cache effects] Explicitly mark unsupported controls in the UI and results; do not call affinity complete isolation.
- [Single-server/single-process capacity] Use one uvicorn worker and SQLite for this version. Add PostgreSQL or a queue when throughput requirements justify them.

## Migration Plan

Local demo → HTTPS server on a private experiment network → batch agent installation → Pi 4 / Pi 5 discovery and bounded experiments → physical KVM-module acceptance. Roll back modules by reloading previously trusted source. Back up databases before upgrades; the initial version does not guarantee migration across versions.

- The KVM module restricts its domain through local environment variables. Structured virsh argv calls discover running state, save original live vCPU affinity, apply changes online, collect domstats, and restore the original affinity in finally. Failure or unconfirmed restoration quarantines the board. KVM does not start or destroy VMs or change guest memory; experiment bundles arrive through authenticated guest-agent access and execute trusted code through manifest argv arrays.

## Artifact execution extension

Address ZIP experiment bundles by SHA-256. Manifests use argv lists for setup/run commands, default environment variables, and output paths; plans support additional arguments and environment overrides. The server stores artifacts by digest, and SQLite records plans, artifact digests, and execution results. Downloads are authorized per board. Limit bundles to 16 MiB compressed, 64 MiB expanded, and 512 members, rejecting symlinks and path traversal. Built-in templates run for at most 120 seconds and custom workloads for at most 86400 seconds. Limit stdout and stderr to 64 KiB each and returned outputs to 512 KiB in total. Explain exceeded limits in the result rather than silently reporting success. Commands run in trusted experiment environments; Linux-user or guest boundaries determine isolation, and temporary directories are not security sandboxes.

Agents pass internally constructed artifact paths and runner snapshots to modules; network clients cannot provide these local paths. KVM uses the QEMU Guest Agent file and guest-exec protocols to transfer a pinned Python runner and ZIP. Guests require Python 3.11+, QGA, and Linux pidfd support to verify process identity during cancellation. The workload template does not accept built-in interference CPU sets; experiments can arrange their own workloads. The simulator only validates artifact arrival and never executes uploaded code. Embed output files in bounded JSON and expose authenticated downloads through the UI and CLI. Larger artifacts, larger outputs, continuous log streaming, and container-image caching are deferred to later versions.

## Product Landing Page and Operator Interface

`/` introduces modular boards, experiment bundles, and CLI/MCP through a landing page with a side-view galaxy disk, restrained entrance effects and parallax, and reduced-motion support. `/console` is a separate operator console; promotional explanations do not occupy the daily management area. The interface does not present demonstrated capabilities as validated on physical hardware.

