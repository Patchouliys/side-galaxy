# Native Core Build and Deployment

Side Galaxy's control-state engine is a C++20 shared library; Python handles HTTP, CLI, MCP, and artifact transfer. Installation must build or provide a native library matching the platform. A missing or incompatible library produces an error instead of switching to a Python scheduler.

## Build Dependencies

Before running `uv sync` or building a wheel, install:

- Python 3.11+ and uv.
- CMake 3.20+.
- A compiler and standard library supporting C++20.
- SQLite headers and link libraries.

Debian / Ubuntu:

```sh
sudo apt-get update
sudo apt-get install -y cmake build-essential libsqlite3-dev
uv sync --frozen
```

On macOS, install Xcode Command Line Tools and CMake. SQLite uses the headers and libraries supplied by the Apple SDK:

```sh
xcode-select --install
brew install cmake
uv sync --frozen
```

The build uses the system toolchain and SQLite. The pinned nlohmann/json header and its license are in `native/vendor/`; CMake configuration does not need to download native dependencies.

## Local Development

The Hatch build hook reads `CMakeLists.txt` at the repository root and builds `side_galaxy_core` in Release mode. An editable installation copies the shared library to `src/side_galaxy/_native/`:

- Linux: `libside_galaxy_core.so`
- macOS: `libside_galaxy_core.dylib`

Build directories and generated shared libraries are ignored by Git. uv cache keys cover CMake files, C++ sources, headers, the build hook, and the compiler environment. Run `uv sync --frozen` after changing native sources to rebuild. To force a rebuild:

```sh
uv sync --frozen --reinstall-package side-galaxy
```

Stop the service before replacing a loaded shared library, then restart it afterward. Python sources remain editable; C++ changes require compilation and are separate from execution-module hot reload.

## Wheels and Source Distributions

```sh
uv build
```

A regular wheel places the shared library in `side_galaxy/_native/` and uses a `py3-none-<platform>` tag, such as `linux_aarch64`, `linux_x86_64`, or `macosx_11_0_arm64`. The C ABI does not depend on the CPython extension ABI, so it is not tied to the Python minor version used for the build. A distribution containing a native library cannot use the universal `any` tag.

Linux wheels dynamically link to the build environment's SQLite, C++ runtime, and libc. An architecture tag does not imply compatibility with every Linux distribution. Build on the target system or a compatible base environment; do not rename a wheel to switch architectures or claim an unsupported `manylinux` tag.

macOS builds target the current runtime architecture. CMake's minimum OS version matches the wheel tag; set `MACOSX_DEPLOYMENT_TARGET` to specify a minimum OS version explicitly.

The source distribution includes the Python package, root CMake configuration, C++ sources, third-party headers and licenses, and `hatch_build.py`, but no precompiled shared library. Installing it requires the build tools listed above.

For Pi 4 / Pi 5 with a 64-bit Linux userspace, build a Linux AArch64 wheel. A macOS ARM64 wheel cannot be deployed to these boards; the current build hook does not configure cross-compilation.

## Container Deployment

```sh
docker build -f deploy/Dockerfile -t side-galaxy .
```

The build stage installs CMake, a compiler, and SQLite development packages, then creates a wheel. The runtime stage installs only the application, pinned Python dependencies, SQLite, and the C++ runtime. Build the image for the control server's architecture.

## Agents on Multiple Boards

`galaxy_wheel` points to a wheel compatible with the target board's architecture and Linux userspace. The example inventory selects a wheel using `ansible_facts.architecture`; individual hosts can override `galaxy_wheel` directly. Preserve the original wheel filename during deployment so pip can validate its platform tag.

```sh
ansible-playbook -i deploy/inventory.local.yml deploy/agents.yml
```

The playbook installs Python, SQLite, and the C++ runtime, without installing a compiler on every board. Prepare wheels for each architecture in advance and keep real device settings and credentials in ignored local files.

## Check Commands

```sh
uv run python -m unittest discover -s tests -v
npm run spec:validate
uv build
```

For build configuration, see the [Hatch build hook](https://hatch.pypa.io/latest/plugins/build-hook/reference/) and [wheel metadata](https://hatch.pypa.io/latest/plugins/builder/wheel/) references. For source-change tracking, see [uv cache keys](https://docs.astral.sh/uv/concepts/cache/#dynamic-metadata).
