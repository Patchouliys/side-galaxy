# CLI and MCP operations

Commands below assume the project environment exposes `sg`; from the source checkout use `uv run sg`. `SG_SERVER` selects the controller and `SG_TOKEN` carries the authorized access token. Keep tokens in private process configuration, never command examples, plans, output, or Git. Remote controller URLs require HTTPS; an existing authorized tunnel may expose HTTP on loopback.

## Discovery and data preparation

```sh
sg workspace
sg profiles
sg boards
sg artifacts
sg environments
```

The catalog describes extensible board/system profiles. The connected board description supplies current execution capabilities; a catalog entry alone does not establish runtime support. Use generic profiles or installed custom profiles as appropriate, without special-casing Raspberry Pi IDs.

For an authorized experiment directory and an already prepared environment directory:

```sh
sg pack experiment --output .data/experiment.zip
sg artifact-upload .data/experiment.zip
sg environment-pack prepared-guest --output .data/environment.zip
sg environment-upload .data/environment.zip
```

Create the ignored output directory if needed. Packing refuses an existing output file. Record each upload's returned SHA-256. An experiment package is at most 16 MiB compressed; environment packages have separate limits and stream through the client. Do not base64-encode a guest image into an MCP message.

Prepared environments contain `environment.json`, `rootfs.raw`, and either bundled firmware or kernel/optional initrd with declared hashes. Use the operations guide for the exact manifest. The trusted backend needs administrator-provided QEMU and the selected acceleration support. Each run gets a fresh writable layer; replay starts from the pinned base image, not a previous run's modifications.

## Plan, queue, and results

Write a private JSON plan, replacing IDs/digests and CPU choices with discovered values. This is a shape example, not a runnable target selection:

```json
{
  "boards": ["RETURNED_BOARD_ID"],
  "template": "workload",
  "cpus": [1],
  "interference_cpus": [],
  "memory_mib": 512,
  "duration_seconds": 60,
  "artifact_sha256": "RETURNED_ARTIFACT_SHA256",
  "environment_sha256": null,
  "arguments": [],
  "environment": {},
  "bandwidth_percent": null,
  "resource_policy": "auto"
}
```

Use an environment digest when the selected runtime requires or intentionally uses a prepared guest. `memory_mib` is the VM budget for guest backends; additionally account for the target's `memory_overhead_mib`. For process backends, inspect returned enforcement evidence rather than assuming a per-process address-space limit covers all descendants. Set `resource_policy` to `cgroup` when process-tree controls are required; unsupported targets fail preflight.

```sh
sg preflight .data/plan.json --enqueue
sg submit .data/plan.json --enqueue --key experiment-intent-001
sg batch BATCH_ID
sg telemetry BOARD_ID --limit 60
sg logs RUN_ID --after 0
sg logs RUN_ID --follow
sg output RUN_ID 0 --output .data/result.json
```

Use `--enqueue` on both preflight and submit to wait for occupied resources. Omit it on both for immediate admission. A retry retains the key and payload above. `sg output` takes an index from the run's output metadata and refuses to overwrite an existing file. `--follow` continues until Ctrl+C; stopping the log reader does not cancel the run. For programmatic log polling, send the returned `next_sequence` as the next exclusive `after` cursor. Preserve `truncated` and final `live_logs_delivery_pending` / `live_logs_truncated` notices.

`sg replay BATCH_ID --boards TARGET_ID --key new-intent-002` (alias `migrate`) reuses the source artifact and parameters after fresh admission. First preflight an equivalent plan with the replacement targets. Replay currently has no `--enqueue` flag; do not invent one. A matching architecture and command contract is useful compatibility evidence, not proof of hardware timing or isolation equivalence.

## MCP mapping

Start with `sg mcp` for read-only tools. `sg mcp --allow-writes` exposes mutations when those operations are authorized; enabling tools does not itself grant permission to act.

| Purpose | Tool and arguments |
|---|---|
| Mode and inventory | `get_workspace()`, `list_boards()`, `list_profiles()`, `list_labs()` |
| Uploaded packages | `list_artifacts()`, `list_environments()` |
| Validate plan | `preflight(plan, enqueue=false)` |
| Device samples | `get_device_telemetry(board_id, limit=60)` |
| Batch and output | `get_batch(batch_id)`, `get_run_logs(run_id, after=0)`, `get_output(run_id, index)` |
| Upload experiment | `upload_artifact(bundle_base64)`; prefer CLI for larger local ZIPs |
| Upload guest | `upload_environment(package_path)`; path is local to the MCP process |
| Submit and replay | `run_experiment(plan, idempotency_key, enqueue=false)`, `replay_experiment(batch_id, boards, idempotency_key)` |
| Cancel | `cancel_batch(batch_id)` |
| Reload trusted module | `reload_module(board_id)`, `force_reload_module(board_id)` |
| Restart managed guest | `restart_lab(instance_id, force=false)`; poll `list_labs()` |

`get_output` returns base64 data and its size. Decode only to the requested local destination. The available MCP schema is authoritative; do not substitute host commands for absent management tools. There is no MCP recover tool.

## Authorized control actions

```sh
sg cancel BATCH_ID
sg reload BOARD_ID
```

Forced reload is `sg reload BOARD_ID --force`. It first interrupts work and waits for cleanup; validation failure or uncertain cleanup can leave the target unavailable. Check board reload acknowledgement and errors rather than treating the request response as completion. A module reload is not a physical host reboot.

After separately verified cleanup and operator authorization, the CLI recovery operation is `sg recover BOARD_ID --cleanup-confirmed`. The flag asserts a real cleanup fact; never add it merely to make admission succeed. Consult the operations guide for host-wide quarantine and service recovery.
