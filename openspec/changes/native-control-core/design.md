# Design

## Context

The current Store owns SQLite transactions and scheduling in Python. API routes, agents, artifact storage and tests call that Store contract. See proposal.md for the migration goal. The database already has a partial unique index enforcing one active lease per board.

## Goals / Non-Goals

Goals: make C++20 the required implementation of the control state engine; preserve schema, response fields, authentication scope, idempotency and cleanup semantics; measure the complete adapter path as well as native work.

Non-goals: change HTTP or MCP protocols, migrate the plugin protocol, replace SQLite, introduce multiple scheduler servers, or translate the Web UI into native code.

## Decisions

- Build one shared library with CMake and system SQLite. A C ABI accepts a database path, operation and bounded JSON payload and returns an owned JSON response. An explicit free function owns deallocation on the C++ side. Native exceptions never cross the boundary. Vendored nlohmann/json v3.12.0 keeps builds independent of network fetches.
- Python ctypes loads the packaged platform library. Missing native binaries produce an actionable error; there is no Python scheduling fallback. Python retains API model validation, cryptographic token/plan hashing, UUID generation and artifact/output transport.
- Native operations cover schema initialization, registration/authentication, heartbeats, board listings, preflight, atomic batch creation, query, claim, finish, cancel, reload and recovery. Each operation opens its own SQLite connection and retains BEGIN IMMEDIATE, foreign keys, WAL and a busy timeout. Result data is copied before connections close.
- Preserve the existing on-disk schema and compare idempotent requests by canonical plan SHA-256. Versions remain pinned at admission. Cleanup failure quarantines boards; cancellation retains the active lease until acknowledgement. Expiry cannot authorize replacement of an unknown running task.
- Artifact existence and validated request models are prepared by the adapter; execution authorization and state transitions remain transactional in the native core. Output downloads continue to enforce size and digest limits in Python.
- Hatch invokes CMake for editable installs and wheels. Wheels carry a platform tag and bundle the shared library. The source distribution carries CMake, native sources, vendored headers and the build hook. Docker uses separate build/runtime stages. Fleet deployment selects wheels for the target architecture.
- Compare repeatable preflight and lifecycle workloads with the previous Python implementation using the same machine, board count and SQLite durability settings. Report latency and throughput without claiming that implementation language alone establishes performance.

## Risks / Trade-offs

- JSON marshalling and SQLite connection/transaction costs can dominate short operations. Measure the public Store boundary before optimizing; keep correctness and durability settings equivalent.
- Native packaging depends on architecture and system libraries. Test wheel contents and installed loading; do not label platform binaries as universal wheels.
- A migration can alter edge-case state transitions. Run existing admission, concurrent submission, cancellation, expiry and module-generation tests against C++ and retain schema compatibility checks.

## Migration Plan

Build the native library, replace Store internals with the adapter, run regression and benchmark workloads, then rebuild application packages and update deployment examples. Stop active service processes before swapping the loaded library. Keep the SQLite schema unchanged so existing registered boards and batches remain accessible.
