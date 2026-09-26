# Verification Record

Initial development acceptance: 2026-09-26 through 2026-09-27, on local macOS ARM64 / Python 3.12. The following results do not constitute Pi hardware or actual KVM acceptance.

| Item | Result | Evidence |
|---|---|---|
| Control-plane core tests | 11 passed (including multiple KVM subcases) | `tests/test_control.py`, `tests/test_modules.py` |
| Multi-board atomicity/idempotency/concurrency | Passed | All-or-nothing batch admission, key reuse, and only one success among four concurrent submissions |
| Permissions/unsupported resources | Passed | Read-only tokens, per-board agent separation, cross-origin rejection, reserved cores, unknown fields, and bandwidth rejection |
| Cancellation/disconnection/persistence | Passed | Leases retained until cancellation acknowledgement, lost-state quarantine, and database reopening |
| Module hot reload | Passed | Valid updates, invalid-version fallback, unchanged output from a running old snapshot, and custom board/OS profiles |
| KVM module restoration logic | Passed with mocked virsh | Restoration on success, statistics failure, and handled cancellation; restoration failures explicitly marked |
| CLI / MCP stdio | Passed against the local service | `scripts/check_integration.py`, official SDK initialize/tools/list/read/preflight/write/results |
| Standalone synthetic agent | Passed against the local service | Registration, heartbeats, task pickup, subprocess execution, result submission, and exit |
| OpenSpec | Strict validation passed | `npm run spec:validate` |
| Python wheel / sdist | Build passed | `uv build --offline` |
| Ansible | Syntax check passed | `ansible-playbook --syntax-check -i deploy/inventory.example.yml deploy/agents.yml` |
| Docker | Not built/run | No local Docker engine; configuration provided |
| Linux process module | Source and protocol checks; not yet executed on Linux | Requires a Pi or Linux target |
| Pi 4 / Pi 5 + KVM | Not executed on hardware | No board addresses or VM/credential details |
| Cache/bandwidth/real-time isolation | Not implemented or claimed | Insufficient capabilities cause request rejection |

Browser checks verified synthetic multi-board selection, preflight, submission, and completed records. Following user feedback, the interface removed large illustrations, slogans, and repeated explanations while retaining brand identity and status design. Subsequent interaction checks and remote CI results depend on actual execution records.

The code is limited to a single node and tenant; whole-workload failure recovery, least privilege for privileged actions, firmware/image lifecycle management, guest injection, PMU, and frequency/thermal-state collection remain future work. The 11 tests above do not replace acceptance of those areas.
