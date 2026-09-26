# Upload and Run Experiment Code on Boards

An experiment bundle combines code, dependency declarations, launch commands, and result paths. The server stores a ZIP version; each target board's agent downloads it, verifies SHA-256, and executes it on the Linux host or inside the KVM experiment VM. Web, CLI, and MCP share the same artifact and batch APIs. Board and OS profiles select the execution module, so bundles do not need hard-coded Pi model names.

Simulated boards exercise artifact distribution and **do not execute uploaded code**. Code execution requires a connected `linux-process` agent or a `linux-kvm` agent whose guest meets the guest-agent requirements.

## Minimal Experiment Directory

The repository's `examples/hello-workload/` directory is ready to package:

```text
hello-workload/
├── experiment.json
├── prepare.py
└── main.py
```

`experiment.json` must be at the ZIP root:

```json
{
  "schema": 1,
  "name": "Python arguments and results example",
  "setup": [["python3", "prepare.py"]],
  "run": ["python3", "main.py"],
  "env": {"EXPERIMENT_LABEL": "baseline"},
  "outputs": ["results/summary.json"]
}
```

`setup` runs in order; a failed step prevents all subsequent steps. `run` is the main experiment command. Each command is an argv array: spaces, quotes, and semicolons are ordinary argument content, with no shell concatenation or variable expansion. Uploaded ARM64 binaries can also run, for example `["./benchmark", "--config", "config.json"]`, provided their architecture and dependencies match the target environment. To run several workloads concurrently, use an entry program inside the bundle that starts and waits for those child processes.

Every execution receives a new, separate working directory. Relative paths in setup and run commands resolve against it. The runner sets `SG_WORKSPACE` to that directory and `PYTHONUNBUFFERED=1` for prompt log output. Only PATH, LANG, LC_ALL, and TZ are inherited, followed by manifest defaults and plan overrides. Do not depend on other environment variables from the control server or agent process.

## Package, Upload, and Submit to Multiple Boards

With the service running and `SG_SERVER` / `SG_TOKEN` configured:

```sh
mkdir -p .data
uv run sg pack examples/hello-workload --output .data/hello-workload.zip
uv run sg artifact-upload .data/hello-workload.zip
uv run sg artifacts
uv run sg boards
```

The upload response includes `sha256`, `size`, and the manifest. Put the digest and actual board IDs into a private `.data/workload-plan.json`:

```json
{
  "boards": ["REPLACE_WITH_BOARD_ID"],
  "template": "workload",
  "artifact_sha256": "REPLACE_WITH_UPLOADED_SHA256",
  "cpus": [1],
  "interference_cpus": [],
  "memory_mib": 256,
  "duration_seconds": 30,
  "arguments": ["--iterations", "5000"],
  "environment": {"EXPERIMENT_LABEL": "pi-comparison"}
}
```

`arguments` are appended to the manifest's `run` command; `environment` overrides manifest defaults. Add multiple board IDs to `boards` to run the same bundle as a batch. All boards must satisfy admission conditions together at submission. Each board executes independently; synchronized starts are not guaranteed. Keep the interference CPU list empty for `workload`; programs inside the bundle create the experiment's workloads.

```sh
uv run sg preflight .data/workload-plan.json
uv run sg submit .data/workload-plan.json --key hello-workload-001
uv run sg batch BATCH_ID
uv run sg output RUN_ID 0 --output .data/summary.json
```

Replace the batch and run IDs with returned values. Output indices start at 0. Use a new key for a new experiment and reuse the original key for network retries of the same submission. Uploaded bundles are pinned by digest. Repackaging and uploading changed code creates a new version; earlier results retain the original digest.

In Web, upload the same ZIP, select the bundle, boards, arguments, and environment, then run preflight and submit. AI tools can inspect artifacts through MCP and submit the same plan. Upload, execution, and cancellation tools require `sg mcp --allow-writes` and an operator token. MCP is read-only by default.

## Dependencies and Runtime

OS configuration and deployment prepare the base environment, including Python, compilers, and drivers. Small projects can install dependencies or compile code in `setup`, for example:

```json
{
  "setup": [["python3", "-m", "pip", "install", "--no-input", "--disable-pip-version-check", "--target", ".deps", "-r", "requirements.txt"]],
  "run": ["python3", "main.py"],
  "env": {"PYTHONPATH": ".deps"}
}
```

This is a manifest fragment; add `schema`, `name`, and the other required fields. The target must already have pip and access to the selected dependency source. Offline experiments can bundle dependencies or preinstall them in a fixed OS or VM image. Installation consumes the experiment's total time budget: setup, run, and collection share `duration_seconds`, with a workload maximum of 86,400 seconds. Each experiment uses a separate working directory; preinstall dependencies in the target environment when they must be reused across tasks.

The Linux module runs experiments with the agent account's permissions. CPU affinity and per-process address-space limits do not provide complete isolation. The KVM module transfers the ZIP and pinned runner into a preconfigured running VM and executes them through QEMU Guest Agent. The guest requires Python 3 and a working QGA; the host continues to manage vCPU affinity through libvirt. Preflight rejects submissions to modules that do not advertise workload support.

## Results, Cancellation, and Limits

Results include `artifact_sha256`, per-step exit codes, stdout and stderr, output files, execution mode, and cleanup evidence. stdout and stderr each retain their first 64 KiB. `stdout_bytes` and `stderr_bytes` report the total captured byte counts; `logs_truncated=true` explicitly indicates incomplete logs. Log truncation alone does not turn exit code 0 into failure. Write complete experiment data to declared output files.

`outputs` collects only the regular files listed in the manifest, without glob expansion. Returned entries contain the path, byte count, SHA-256, and bounded base64 data; UI and CLI downloads reconstruct the original files. A missing declared file, link, special file, change during reading, or total size above 512 KiB fails the experiment. Previously collected files may remain in the result and must not be treated as the complete output set.

ZIP bundles are limited to 16 MiB compressed, 64 MiB expanded, and 512 members. Validation rejects path traversal, absolute paths, backslashes, duplicate paths, file/directory conflicts, links, encrypted ZIP files, invalid manifests, and corrupt CRCs. Paths that collide after case folding or Unicode normalization are also rejected for consistency across filesystems. Only stored and deflate compression are supported.

Cancellation and timeout request termination of process groups started by the runner, then force termination when needed, recording `cleanup[].group_gone`. Unconfirmed cleanup sets `cleanup_ok=false`; the platform should retain quarantine until an operator verifies recovery. The experiment entry point must wait for its children to exit. It must not daemonize, call setsid to leave the process group, or create unmanaged persistent services. Such workloads require a dedicated execution module and cleanup protocol.

Experiment code is trusted operator code. A working directory is not a sandbox for hostile code. Use a dedicated low-privilege account or KVM guest when additional isolation is required. Do not upload unknown code and execute it directly on boards with production privileges. The server distributes experiment artifacts; administrators still deploy and hot-reload management modules locally.
