"""Thin, owned-memory binding to the required C++ control engine."""
import ctypes
from functools import lru_cache
import json
from pathlib import Path
import sys


class NativeError(ValueError):
    def __init__(self, kind, message):
        self.kind = kind
        super().__init__(message)


@lru_cache(maxsize=1)
def library():
    suffix = '.dylib' if sys.platform == 'darwin' else '.so'
    path = Path(__file__).with_name('_native') / ('libside_galaxy_core' + suffix)
    if not path.is_file():
        raise RuntimeError('Native control core is missing. Install CMake, a C++20 compiler and SQLite development files, then run uv sync --reinstall-package side-galaxy.')
    core = ctypes.CDLL(str(path))
    core.sg_core_abi_version.argtypes = []
    core.sg_core_abi_version.restype = ctypes.c_int
    if core.sg_core_abi_version() != 1:
        raise RuntimeError('Incompatible native core ABI; rebuild Side Galaxy')
    core.sg_core_call.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p]
    core.sg_core_call.restype = ctypes.c_void_p
    core.sg_core_free.argtypes = [ctypes.c_void_p]
    core.sg_core_free.restype = None
    return core


def call(path, operation, payload=None):
    core = library()
    data = json.dumps(payload or {}, ensure_ascii=False, separators=(',', ':')).encode()
    pointer = core.sg_core_call(str(path).encode(), operation.encode(), data)
    if not pointer: raise RuntimeError('Native control core could not allocate a response')
    try: response = json.loads(ctypes.string_at(pointer))
    finally: core.sg_core_free(pointer)
    if not response['ok']:
        error = response['error']
        raise NativeError(error['kind'], error['message'])
    return response['value']
