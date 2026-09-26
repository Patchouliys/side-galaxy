# Tasks

## 1. Native state engine

- [x] 1.1 Implement the C++20 SQLite engine and C ABI with fixed dependency provenance; verify CMake build and native checks.
- [x] 1.2 Replace Python scheduling logic with the native adapter; verify existing admission, concurrency, idempotency, expiry, cancellation and result tests against the shared library.
- [x] 1.3 Preserve existing database and request compatibility; verify loading a database created by the previous implementation and document the core boundary.

## 2. Build and deployment

- [x] 2.1 Package the mandatory native library in editable installs, platform wheels and source distributions; verify fresh installation and library loading.
- [x] 2.2 Adapt Docker, CI and multi-board wheel selection; verify syntax/configuration and publish usable build instructions.

## 3. Performance and integration

- [x] 3.1 Add a repeatable benchmark and compare native and previous Store implementations with equivalent workloads and durability settings; report measured latency and throughput.
- [x] 3.2 Run HTTP, CLI and MCP workflows against the native core, validate OpenSpec, and commit the complete integration using the repository owner's GitHub identity.
