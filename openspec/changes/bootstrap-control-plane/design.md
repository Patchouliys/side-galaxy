# Design

## Context

Development started from an empty repository. The initial targets are Pi 4 and Pi 5, with a public GitHub repository and hot-reloadable management modules. Linux with KVM is the selected virtualization platform. See proposal.md for motivation.

## Goals / Non-Goals

Goals: A complete control-plane workflow, independent agents, a module protocol, deployable source code, and Linux process and KVM execution modules.

Non-Goals: Jailhouse control, hard real-time scheduling, MPAM, cache partitioning, and synchronized multi-board barriers.

## Decisions

- Use Python, FastAPI, Pydantic, SQLite, and native HTML/CSS/JS to simplify deployment on one server and local development. Use the maintained v1 API of the official Python MCP SDK, pinned below v2, instead of implementing the protocol manually.
- The server orchestrates; agents poll outbound using separate board tokens. Web, CLI, and MCP use operator or read-only tokens. A reverse proxy or SSH tunnel provides transport protection. Local demo mode must be enabled explicitly, and the browser keeps its token only in memory.
- Grant one job lease per board, with victim and interferer workloads allowed inside that experiment. Use SQLite `BEGIN IMMEDIATE` for atomic batch admission. Introduce resource-graph scheduling only when concurrent experiments on one board are required.
- Requests specify boards, templates, victim and interference CPU sets, memory, and duration. Preflight runs before submission, and submission repeats validation. Unsupported capabilities, offline boards, quarantine, and resource conflicts produce explicit errors.
- Track queued, running, cancelling, succeeded, failed, cancelled, and lost states. Cancellation cannot release resources before agent confirmation. Lost boards are quarantined and require explicit recovery after workload termination is verified. The design does not claim distributed exactly-once execution.
- SQLite stores plans and their SHA-256 hashes, module hashes, and results. Demo mode can execute simulators inside the server; independent agents support simulator and Linux process execution modules.
- Represent board profiles as data. Modules are trusted, administrator-deployed standalone Python files using a stdin/stdout JSON protocol. Copy source into private snapshots named by SHA-256 before probing and executing it. Start each job in a new process group. Remote management APIs cannot upload module source or specify host-local paths. Hot reload occurs at idle polling boundaries; running processes retain their original snapshots, and failed reloads preserve the previous generation. Subprocesses provide fault containment, not a security sandbox for malicious plugins.
- The Linux module provides process affinity, address-space limits, and bounded microbenchmarks. CPU 0 is reserved for management by default. Other host processes can still use the same CPUs; these controls do not replace a hypervisor, cgroups, or resctrl. Experiment bundle execution extends the same process controls as described below.
- Use an original SVG identity: a horizontal elliptical galaxy disk, tilted orbit, and bright core, with deep navy, cyan, and warm white. Avoid external fonts and tracking resources.

## Risks / Trade-offs

- [Hardware variation] Discover capabilities on each board instead of inferring support from the model name.
- [Malicious or uncontrolled plugins] Restrict module deployment to trusted administrators, terminate process groups on timeout, and use narrowly scoped helpers for future privileged operations.
- [Uncontrolled shared-cache effects] Mark unsupported controls explicitly in the UI and results. Do not describe CPU affinity as complete isolation.
- [Single-server and single-process limits] Use one uvicorn worker and SQLite initially. Introduce PostgreSQL or a queue only when measured throughput requires them.

## Migration Plan

Deploy an HTTPS server on the experiment network, install agents in batches, discover capabilities on Pi 4 and Pi 5, and configure bounded Linux or KVM experiments.

The KVM module limits its target domain through local environment configuration. Structured virsh arguments discover its running state, save original live vCPU affinity, apply the experiment affinity, collect `domstats`, and restore the original affinity in `finally`. Failure or unconfirmed restoration quarantines the board. The module does not start or destroy VMs or change guest memory. Experiment bundles travel through authenticated guest-agent access and run trusted commands declared as manifest argv arrays.

## Artifact Execution

Address ZIP experiment bundles by SHA-256. Their manifests declare `setup` and `run` argv arrays, default environment variables, and output paths; plans can append arguments and override environment variables. The server stores artifacts by digest. SQLite records plans, artifact digests, and execution results. Artifact downloads require authorization for the target board.

Limit compressed bundles to 16 MiB, expanded contents to 64 MiB, and archives to 512 members. Reject symbolic links and path traversal. Built-in templates run for at most 120 seconds; custom workloads run for at most 86400 seconds. Bound stdout and stderr to 64 KiB each and returned output files to 512 KiB in total. Report exceeded limits in the result rather than silently reporting success. Commands run in a trusted experiment environment, with isolation determined by the Linux user or guest boundary; temporary directories are not a security sandbox.

Agents pass internally constructed artifact paths and runner snapshots to modules; network requests cannot supply these local paths. KVM uses the QEMU Guest Agent file and `guest-exec` protocols to transfer a pinned Python runner and ZIP. Guests require Python 3.11 or newer, QGA, and Linux pidfd support for process identity checks during cancellation. The `workload` template does not accept built-in interference CPU sets; the experiment can organize its own workload roles. Simulators only verify artifact delivery and never execute uploaded code.

Embed output files in bounded result JSON and expose authenticated downloads through the UI and CLI. Larger artifacts, larger outputs, continuous log streaming, and container image caching are deferred.

## Product Introduction and Console

`/` introduces modular boards, experiment bundles, and CLI/MCP access through a landing page with a galaxy viewed from the side, restrained entrance effects, and parallax that respects reduced-motion preferences. `/console` is a separate working console. Promotional explanations do not consume the main management area.

The main visual uses native Canvas 2D with separate layers for the galactic core, animated dust disk, trails, and subtle parallax. Bound device pixel ratio and particle count, pause animation when the page is hidden, and render a static frame when reduced motion is preferred. No graphics library dependency is required.
