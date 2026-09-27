# Tasks

## 1. Native queue

- [x] 1.1 Implement persistent opt-in waiting batches, fair atomic dispatch and idempotency; verify FIFO, independent targets, cancellation, restart, generation and quarantine tests.
- [x] 1.2 Preserve late completion evidence without auto-recovery and document queue semantics in the operations guide; verify lost-run regression tests.

## 2. Offline environments

- [x] 2.1 Implement bounded environment packaging, streaming storage and verified extraction; test traversal, links, size limits, integrity and deduplication and document the package contract.
- [x] 2.2 Implement QEMU guest execution with fresh overlays, identity-checked stop, offline guest transfer and cleanup evidence; test lifecycle failure paths and run a prepared guest with reported accelerator evidence.
- [x] 2.3 Connect environment upload and selection to agent staging, HTTP, CLI and MCP; verify authorization, hashes and compatibility with existing workload plans.

## 3. Running output and controls

- [x] 3.1 Add bounded sequenced log capture, authenticated storage and resumable retrieval; verify ordering, retries, ownership, limits and actual running output.
- [x] 3.2 Add environment selection, queue status and live logs to the console; verify interaction checks and desktop/narrow layouts.
- [x] 3.3 Confirm process-group cleanup before reporting release and align service stop deadlines; test uncertain-cleanup handling and update operational guidance.

## 4. Integrated execution

- [x] 4.1 Deploy through private offline staging and run a real physical Linux workload, queue, cancellation, reload and output retrieval; retain evidence and backups only in ignored local files.
- [ ] 4.2 Run required Python/native checks, strict OpenSpec validation and interface checks; inspect public changes for private data and publish with the repository owner's identity.
