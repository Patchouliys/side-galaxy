"""Build the required C++ core for native-host wheels and editable installs."""
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
import sysconfig

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        cmake = shutil.which("cmake")
        if not cmake:
            raise RuntimeError("Side Galaxy requires CMake 3.20+, a C++20 compiler, and SQLite development files. See docs/native-build.md.")
        system, machine = platform.system(), platform.machine()
        if system not in ("Linux", "Darwin"):
            raise RuntimeError("Native Side Galaxy builds currently support Linux and macOS hosts.")
        root = Path(self.root)
        options = []
        if system == "Darwin":
            target = os.environ.get("MACOSX_DEPLOYMENT_TARGET") or sysconfig.get_config_var("MACOSX_DEPLOYMENT_TARGET")
            target = target or ".".join(platform.mac_ver()[0].split(".")[:2])
            if not re.fullmatch(r"\d+(?:\.\d+){0,2}", target):
                raise ValueError("MACOSX_DEPLOYMENT_TARGET must be a numeric macOS version.")
            major, minor = (target.split(".") + ["0"])[:2]
            tag = f"macosx_{major}_{minor}_{machine}"
            options += [f"-DCMAKE_OSX_DEPLOYMENT_TARGET={target}", f"-DCMAKE_OSX_ARCHITECTURES={machine}"]
            filename = "libside_galaxy_core.dylib"
        else:
            tag, filename = f"linux_{machine}", "libside_galaxy_core.so"
        directory = root / "build" / ("native-" + tag)
        staging = directory / "install"
        # Keep developer paths out of __FILE__ strings and debug records in distributed binaries.
        flags = os.environ.get("CXXFLAGS", "") + " " + shlex.quote(f"-ffile-prefix-map={root}=.")
        subprocess.run([cmake, "-S", str(root), "-B", str(directory),
                        "-DCMAKE_BUILD_TYPE=Release", "-DBUILD_TESTING=OFF", f"-DCMAKE_INSTALL_PREFIX={staging}",
                        f"-DCMAKE_CXX_FLAGS={flags}", *options], check=True)
        subprocess.run([cmake, "--build", str(directory), "--target", "side_galaxy_core",
                        "--config", "Release", "--parallel", "2"], check=True)
        subprocess.run([cmake, "--install", str(directory), "--config", "Release"], check=True)
        library = staging / "side_galaxy" / "_native" / filename
        if not library.is_file():
            raise RuntimeError("CMake did not install the required Side Galaxy native library.")
        build_data["pure_python"] = False
        build_data["tag"] = "py3-none-" + tag
        if version == "editable":
            destination = root / "src" / "side_galaxy" / "_native" / filename
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_suffix(destination.suffix + ".tmp")
            shutil.copy2(library, temporary)
            os.replace(temporary, destination)
        else:
            build_data["force_include"][str(library)] = "side_galaxy/_native/" + filename
