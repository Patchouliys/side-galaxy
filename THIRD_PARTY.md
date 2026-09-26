# Third-party material

- OpenSpec 1.13.2: https://github.com/Fission-AI/OpenSpec — MIT. Generated skills in `.agents/skills/openspec-*`; license in `licenses/openspec-MIT.txt`. Dev dependency is version-locked; project npm scripts set OPENSPEC_TELEMETRY=0 and DO_NOT_TRACK=1.
- Ponytail: https://github.com/DietrichGebert/ponytail — commit `e3ba2aa6f1e6f0bc4d69eb09c9f0d0a93af56156`, MIT. Unmodified skill and license in `.agents/skills/ponytail/SKILL.md` and `licenses/ponytail-MIT.txt`.
- Runtime dependencies are recorded in `pyproject.toml` and `uv.lock`; each retains its own license.
- Raspberry Pi names identify compatible target profiles; this project is not affiliated with Raspberry Pi Ltd.

## nlohmann/json

- Source: https://github.com/nlohmann/json/releases/tag/v3.12.0
- Version: v3.12.0 (vendored single-header library for the C++ control core).
- License: MIT, preserved in `native/vendor/nlohmann/LICENSE.MIT`.
- Header: `native/vendor/nlohmann/json.hpp`.
- SHA-256: `aaf127c04cb31c406e5b04a63f1ae89369fccde6d8fa7cdda1ed4f32dfc5de63`.
