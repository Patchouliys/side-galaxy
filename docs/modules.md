# Module Development and Hot Reload

Board and system manifests live in `src/side_galaxy/profiles/boards/` and `systems/`. The control plane does not enumerate Pi models or OS names. Agent startup arguments select manifest IDs. Use `--profiles-dir /etc/side-galaxy/profiles` for additional agent manifests and `SG_PROFILES_DIR` for the server's manifest directory; deploy these separately.

Example board profile, saved as `boards/custom-board.json`:

```json
{"id":"custom-board","name":"Custom board","architecture":"aarch64","soc":"custom","reserved_cpus":[0]}
```

Example system profile, saved as `systems/custom-linux.json`:

```json
{"id":"custom-linux","name":"Custom Linux","module":"linux_process","requires":"Linux sched_setaffinity"}
```

`architecture`, `soc`, and `expected_cores` are declarations, not hardware discovery results. Admission uses the CPUs, memory, reserved CPUs, capabilities, and templates reported by the module. The initial agent requires Python 3.11+ and POSIX process groups. Extensible manifests do not mean that Windows, bare-metal, or RTOS targets are already supported; those targets require a compatible agent or bridge module in a Linux management domain or on an external controller.

## Standalone Module Protocol v1

A trusted administrator deploys a standalone Python file, selected by the agent through `--module-file /opt/side-galaxy/modules/custom.py`. Network interfaces cannot submit module paths or source code. The file must depend only on the standard library or explicitly deployed packages; relative imports from sibling files do not work with single-file content snapshots. Complex modules may later use versioned packages with manifests.

Each invocation starts a new process. stdin contains one JSON value, stdout must contain exactly one JSON object, and diagnostics go to stderr. The agent does not upload stderr.

Discovery input: `{"op":"describe"}`. Example output:

```json
{
  "protocol":1,"name":"Custom runtime","mode":"custom-linux",
  "cpus":[0,1,2,3],"reserved_cpus":[0],"memory_mib":1024,
  "capabilities":["cpu-affinity","memory-limit","interference"],
  "templates":["cpu-contention"],"cleanup_scope":"process-group"
}
```

The agent computes and injects `module_sha256`; the plugin does not report it. New IDs are allowed for `mode` and template names. Declare `capabilities` only for controls the module actually implements. Declare `bandwidth-limit` only when the backend supports it. The KVM module declares only CPU affinity as a resource control.

Execution input: `{"op":"run","plan":{...},"run_id":"UUID"}`. Workloads also receive absolute `artifact_path` and `runner_path` values constructed internally by the agent. Output includes `cleanup_ok`, `mode`, `synthetic`, results, and boot IDs before and after execution. KVM output records saved, applied, and restored affinity, plus libvirt statistics. `cleanup_ok:false` or unknown cleanup results quarantine the board. Use `cleanup_scope:process-group` only when all managed resources belong to the child process group. Modules that modify guest, sysfs, cgroup, or peripheral state must use the default `external` scope and restore and report that state themselves.

## Hot Reload Semantics

1. While idle, the agent reads the source and both manifests, computes their combined SHA-256, and copies the source into a private read-only snapshot.
2. A new snapshot replaces the current generation only after passing describe-protocol validation. Errors report only their type; the previous generation remains in use.
3. New tasks pin a generation. Running tasks do not reimport or replace their implementation.
4. Idle polling automatically discovers changes to the same source file. `sg reload BOARD_ID`, Web, or MCP can explicitly request rediscovery.
5. Requested reloads are handled after execution and result submission finish. Board queries expose reload errors; acknowledging a request does not mean the new generation loaded successfully.
6. A generation change after admission causes the queued task to be rejected. Run preflight again before resubmitting. To roll back, restore previously validated source and manifests, then reload.

Process modules have time limits. On timeout, the agent first sends SIGTERM, then forcibly terminates the process group after 10 seconds. Handled KVM cancellation attempts restoration in `finally`; SIGKILL, power loss, or a host crash cannot guarantee restoration. Unknown state therefore quarantines the board. Verify live pinning manually before using `sg recover BOARD_ID --cleanup-confirmed`. Do not use recovery to bypass cleanup.

KVM operations are restricted to the dedicated experiment VM selected by the agent's local `SG_KVM_DOMAIN` environment variable, initially resolved to a UUID. Administrators should configure the agent's libvirt permissions for that VM. Concurrent changes by other tools invalidate the snapshot-and-restore assumptions and must be prohibited during experiments.

Execution modules declare built-in templates through `templates`. The `workload` template executes a ZIP bundle identified by SHA-256; its manifest declares setup/run argv arrays, environment variables, and outputs. See [experiment bundles](workloads.md). Digest verification is implemented; signatures are not yet implemented. Administrators still deploy management-module source locally on the board. Descriptions may set `memory_limit_required:true`; shared preflight then rejects plans without a memory budget. The module generation digest also covers the runner and board/system descriptions. Running code is never replaced.
