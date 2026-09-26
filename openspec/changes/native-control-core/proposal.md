# Proposal

## Why

Resource admission, multi-board scheduling and task state transitions need a native C++ core. The existing HTTP, CLI and MCP contracts should remain stable while the implementation and its deployment toolchain change.

## What Changes

- Move the SQLite-backed control state engine from Python to C++20, including board registration, heartbeats, capability checks, atomic admission, idempotency, leases, cancellation and quarantine.
- Expose a small C ABI; keep Python as the HTTP/CLI/MCP and artifact transport layer, without a Python scheduling fallback.
- Build and package the native library with CMake, retaining the existing database schema and control API.
- Add repeatable comparative measurements and run the lifecycle and concurrency regression suite against the native implementation.
- Update source, wheel, container and multi-board deployment instructions for platform-specific binaries.

## Capabilities

### New Capabilities

None. This change replaces the implementation of the existing control-plane contract.

### Modified Capabilities

None. Existing fleet-control and module-runtime semantics remain unchanged. Delta specs are skipped for this implementation refactor.

## Impact

The control state engine, Python Store adapter, wheel build hook, CMake configuration, CI and deployment files change. Builds require CMake, a C++20 compiler and SQLite development files. The existing database remains readable. nlohmann/json is vendored at a fixed MIT-licensed version. Python execution modules remain replaceable protocol adapters; the native scheduling engine becomes mandatory.
