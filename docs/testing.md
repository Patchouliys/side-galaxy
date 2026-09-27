# Tests and Checks

Run the following commands from the repository root. Requirements are Python 3.11+, uv, CMake 3.20+, a C++20 compiler, SQLite development headers, and Node.js / npm for OpenSpec. See the [native build guide](native-build.md) for platform toolchains.

## Install Development Dependencies

```sh
uv sync --frozen
npm ci --ignore-scripts
```

`uv sync` builds and installs the required native library. Python interface tests invoke the C++ core through the native bridge; a missing or incompatible library fails directly instead of using a Python scheduler substitute.

## Automated Tests and Specification Checks

```sh
uv run python -m unittest discover -s tests -v
npm run spec:validate
node --check src/side_galaxy/static/app.js
node --check src/side_galaxy/static/homepage.js
node scripts/check_homepage_story.cjs
```

To select a test file, for example:

```sh
uv run python -m unittest discover -s tests -p 'test_execution_transport.py' -v
```

## Native Core Tests

Build the C++ core separately and run CTest:

```sh
cmake -S . -B build/native-check -DCMAKE_BUILD_TYPE=Debug -DBUILD_TESTING=ON
cmake --build build/native-check
ctest --test-dir build/native-check --output-on-failure
```

This build directory is for native tests. `uv sync` manages the native library installed in the Python environment; after changing C++ sources, rerun `uv sync --frozen` before running Python interface tests.

## HTTP, CLI, MCP, and Agent Integration

Start a separate demo database in one terminal:

```sh
uv run sg serve --demo --db .data/integration.db
```

In another terminal, run:

```sh
uv run python scripts/check_integration.py
```

The script registers a synthetic agent with the demo service, uploads a bundle, and creates experiment records. The default address is `http://127.0.0.1:7980`; set `SG_SERVER` when using another local demo port.

## Build and Deployment Configuration

```sh
uv build
ansible-playbook --syntax-check -i deploy/inventory.example.yml deploy/agents.yml
```

Ansible syntax checks require Ansible on the control machine. The wheel contains a platform-native library and should be built in an environment compatible with the target CPU architecture and system ABI.
