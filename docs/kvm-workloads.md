# Linux / KVM Experiment Bundle Execution

The platform accepts ZIP archives containing `experiment.json` and experiment code. The server stores the artifact; the board agent downloads it and verifies its SHA-256. The agent passes the verified local artifact path and a pinned runner version to the execution module. The network API does not accept management-module source, module paths, or host shell text. Manifest `setup` / `run` entries are structured argv for trusted experiment code; additional arguments, environment variables, and output files are managed by the same plan.

## Linux Host Processes

The `linux-process` module supports `workload` and runs the bundle in a newly created temporary workspace. It sets Linux CPU affinity and `RLIMIT_AS` before starting the runner. Failure at either step fails the run instead of falling back to unrestricted execution. Child processes inherit these settings.

- `cpus` is the set of permitted host CPUs; CPU 0 is reserved by default.
- `memory_mib` must be at least 128 and includes the runner's own address space. This is a **per-process virtual address-space limit**, not an aggregate memory quota for multiple processes or a physical memory reservation.
- `duration_seconds` limits the entire experiment. Bundles may run for at most 86400 seconds (24 hours); built-in microbenchmarks are limited to 120 seconds. `interference_cpus` must be empty; programs in the bundle organize their own experiment roles.
- Hardware bandwidth limits are not supported. CPU affinity does not guarantee exclusive cores, cache isolation, or real-time behavior.

Experiments run as the agent user. Workspaces and process limits are not a security sandbox. Run only trusted bundles and avoid programs that use daemonize / setsid to escape the runner's management. On cancellation, the runner terminates and checks the process groups it started. If it cannot confirm cleanup, it retains the workspace and returns `cleanup_ok: false`; the control plane quarantines the board for administrator inspection.

## KVM Guest Distribution

The board needs libvirt, `virsh`, and an **administrator-selected, dedicated, running Linux VM**. The agent reads `SG_KVM_DOMAIN` only from its local environment and pins the VM identity through `domuuid`. User plans cannot select another domain or provide a libvirt URI. `SG_LIBVIRT_URI` defaults to `qemu:///system`.

The guest requires:

1. QEMU Guest Agent installed and enabled, with its virtio channel configured in libvirt.
2. Python 3.11 or newer at `/usr/bin/python3`, and Linux pidfd signaling support.
3. A Guest Agent policy permitting `guest-ping`, `guest-exec`, `guest-exec-status`, and `guest-file-open/write/close`.
4. Preinstalled experiment dependencies. Compiled bundles must provide binaries matching the guest architecture or invoke an installed toolchain in `setup`.

The module advertises the `workload` template only after successful probing. If Guest Agent is unavailable, `kvm-affinity` can still set live CPU affinity and collect statistics for the existing VM, but experiment bundles cannot be uploaded and executed.

Execution sequence:

1. Save all live vCPU affinities, bind vCPUs to the plan's **host CPU set**, and collect `domstats`.
2. Create a unique `/tmp/side-galaxy/<run UUID>/`. Reject reuse if the directory already exists, its parent is a symbolic link, or its parent is writable by other users.
3. Write the ZIP and pinned runner in chunks through the Guest Agent file protocol. Handle short writes and attempt to close every handle on completion or failure. Transfer is limited to 60 seconds.
4. Guest Python verifies the ZIP and runner digests, then runs `runner.py --bundle … --workspace …/work --plan …`. All arguments use argv; the module does not construct shell commands.
5. Poll process status and collect the final exit code, stdout, stderr, steps, output files, and cleanup evidence. Guest Agent output truncation fails the run and cannot be treated as a complete result.
6. After the runner confirms its process groups have ended, remove this UUID's temporary directory, then restore and verify the original live affinity.

For KVM, `memory_mib` must be `null`; the module does not change VM memory. Host CPU numbers are not reused as guest CPU numbers. Bundle programs can organize parallel workloads inside the guest.

Cancellation runs a fixed Python helper through Guest Agent: it checks that the process command contains this run's runner path, sends SIGTERM to the runner through pidfd, and waits for its final JSON cleanup evidence. If Guest Agent disconnects, the launch acknowledgment is lost, runner output is invalid, workspace removal fails, or live affinity restoration fails, `cleanup_ok` is `false`. Available PID, workspace, and phase information is retained for administrator inspection; the VM or board is not automatically rebooted.

Guest Agent usually has extensive guest privileges, so this is intended only for trusted experiments and dedicated VMs; it does not provide multitenant code isolation. Bundles can run for up to 24 hours. Persistent hosting of network services and background daemons is outside this version's batch experiment protocol.

`cleanup_ok` checks the runner's process groups, task temporary directory, and KVM live affinity. Software installed by the bundle, system configuration changes, and files written outside the workspace are not automatically rolled back. Keep `setup` repeatable; full guest-state restoration requires a separate image or snapshot management workflow.

## Results and Acceptance Scope

Results include execution mode, artifact and runner digests, boot IDs before and after execution, KVM domain UUID, original/applied/restored affinities, and runner logs and outputs. The control plane separately pins the module generation and request digest. Matching boot IDs only show that the observed host boot identifier has not changed; they do not demonstrate isolation performance.

`tests/test_execution_transport.py` covers QGA chunked transfer, short writes, cancellation, lost launch acknowledgments, log truncation, cleanup failure, and restoration of the original affinity, using mocked QGA responses. Linux startup-limit failure paths are also tested. **These tests do not constitute Pi 4, Pi 5, or real KVM acceptance.** Hardware validation must still check Guest Agent permissions, file-transfer throughput, cancellation latency, actual affinity, boot IDs, experiment outputs, and recovery after failure.

Protocol references: [QEMU Guest Agent protocol](https://www.qemu.org/docs/master/interop/qemu-ga-ref.html), [libvirt virsh](https://www.libvirt.org/manpages/virsh.html#qemu-agent-command).
