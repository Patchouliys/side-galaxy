# Verification Record

Initial development acceptance: 2026-09-26 through 2026-09-27, on local macOS ARM64 / Python 3.12. The following results do not constitute Pi hardware or actual KVM acceptance.

| Item | Result | Evidence |
|---|---|---|
| Control-plane core tests | 42 passed (including KVM failure subcases and a real example program) | `tests/test_control.py`, `tests/test_modules.py`, `tests/test_workloads.py`, `tests/test_execution_transport.py`, `tests/test_artifact_api.py` |
| Multi-board atomicity/idempotency/concurrency | Passed | All-or-nothing batch admission, key reuse, and only one success among four concurrent submissions |
| Permissions/unsupported resources | Passed | Read-only tokens, per-board agent separation, cross-origin rejection, reserved cores, unknown fields, and bandwidth rejection |
| Cancellation/disconnection/persistence | Passed | Leases retained until cancellation acknowledgement, lost-state quarantine, and database reopening |
| Module hot reload | Passed | Valid updates, invalid-version fallback, unchanged output from a running old snapshot, and custom board/OS profiles |
| KVM module restoration logic | Passed with mocked virsh | Restoration on success, statistics failure, and handled cancellation; restoration failures explicitly marked |
| CLI / MCP stdio | Passed against the local service | `scripts/check_integration.py`, official SDK initialize/tools/list/read/preflight/write/results |
| Standalone synthetic agent | Passed against the local service | CLI packaging/upload, registration, heartbeats, task-authorized downloads, digest checks, synthetic result submission, and exit |
| OpenSpec | Strict validation passed | `npm run spec:validate` |
| Python wheel / sdist | Build passed | `uv build --offline` |
| Ansible | Syntax check passed | `ansible-playbook --syntax-check -i deploy/inventory.example.yml deploy/agents.yml` |
| Docker | Not built/run | No local Docker engine; configuration provided |
| Linux process module | Real bundle → module → runner passed; affinity/RLIMIT_AS mocked in macOS tests, not yet executed on a Linux target | Requires a Pi or Linux target |
| Pi 4 / Pi 5 + KVM | Not executed on hardware | No board addresses or VM/credential details |
| Cache/bandwidth/real-time isolation | Not implemented or claimed | Insufficient capabilities cause request rejection |

Browser checks verified the redesigned console's two-board selection, bundle parameters, preflight, submission, final logs, cancellation entry point, and module reload; the separate promotional homepage entry point works. Upload/download authorization and file digests were verified through API/CLI/MCP and automated tests, not by actually selecting files for upload or downloading results in the browser. The interface retains the edge-on galaxy identity, with promotional effects on the separate homepage.

The code is limited to a single node and tenant. Artifacts are limited to 16 MiB compressed and 64 MiB extracted, stdout/stderr to 64 KiB each, and total outputs to 512 KiB; logs return after the task finishes. Full guest snapshot restoration, production RBAC/auditing, firmware/image lifecycle management, PMU, and frequency/thermal-state collection remain future work. These tests do not replace hardware, permission, or resource-isolation acceptance.

Added regression coverage: ZIP paths/special files/CRC/tampering, FIFO packaging and cumulative extraction limits, cross-board artifact authorization, expired tasks not starting, plan length, total result size/digest validation, bounded downloads, setup failures, timeouts/cancellation, and process-tree cleanup.
