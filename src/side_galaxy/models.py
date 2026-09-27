import re
import json
import base64
import hashlib
from .workload_runner import MAX_OUTPUTS, relative_path
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Plan(Strict):
    boards: list[str] = Field(min_length=1, max_length=32)
    template: str = Field(default="cpu-contention", pattern=r"^[a-z0-9-]{1,64}$")
    cpus: list[int] = Field(default=[1], min_length=1, max_length=64)
    interference_cpus: list[int] = Field(default=[2], max_length=64)
    memory_mib: int | None = Field(default=256, ge=128, le=65536)
    duration_seconds: int = Field(default=5, ge=1, le=86400)
    artifact_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    environment_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    arguments: list[str] = Field(default_factory=list, max_length=64)
    environment: dict[str, str] = Field(default_factory=dict, max_length=64)
    bandwidth_percent: int | None = Field(default=None, ge=1, le=100)
    resource_policy: Literal['auto', 'cgroup'] = 'auto'

    @model_validator(mode="after")
    def unique(self):
        if self.template == "workload":
            if not self.artifact_sha256: raise ValueError("Workload requires an uploaded artifact")
            if self.interference_cpus: raise ValueError("Workload owns its commands; leave interference_cpus empty")
        elif self.artifact_sha256 or self.arguments or self.environment:
            raise ValueError("Artifact, arguments and environment require workload template")
        elif self.duration_seconds > 120:
            raise ValueError("Built-in templates allow at most 120 seconds")
        if any(len(a) > 4096 or "\0" in a for a in self.arguments):
            raise ValueError("Invalid or oversized argument")
        if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", k) or len(v) > 4096 or "\0" in v for k, v in self.environment.items()):
            raise ValueError("Invalid or oversized environment entry")
        if len(json.dumps(self.model_dump(), ensure_ascii=True)) > 32768:
            raise ValueError("Plan exceeds 32 KiB serialized limit")
        if self.environment_sha256 and self.template != "workload":
            raise ValueError("Prepared environments require a workload bundle")
        cores = self.cpus + self.interference_cpus
        if len(set(cores)) != len(cores) or any(c < 0 for c in cores):
            raise ValueError("Core sets must be nonnegative, unique and disjoint")
        if len(set(self.boards)) != len(self.boards):
            raise ValueError("Duplicate board IDs")
        return self


class Enrollment(Strict):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[\w .-]+$")
    board_profile: str = Field(default="generic", pattern=r"^[a-z0-9-]{1,64}$")
    system_profile: str = Field(default="linux-process", pattern=r"^[a-z0-9-]{1,64}$")


class ExecutionEnvironment(Strict):
    architecture: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,31}$")
    os: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,31}$")
    commands: list[Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")]] = Field(default_factory=list, max_length=4096)
    commands_complete: bool = False


class Description(Strict):
    protocol: Literal[1] = 1
    name: str = Field(max_length=64)
    mode: str = Field(pattern=r"^[a-z0-9-]{1,64}$")
    cpus: list[int] = Field(min_length=1, max_length=1024)
    reserved_cpus: list[int] = Field(default=[0], max_length=1024)
    memory_mib: int = Field(ge=128, le=16777216)
    capabilities: list[str] = Field(max_length=64)
    templates: list[str] = Field(min_length=1, max_length=64)
    module_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    memory_limit_required: bool = False
    environment_required: bool = False
    execution_environment: ExecutionEnvironment | None = None
    environment_architectures: list[Literal["aarch64", "x86_64"]] = Field(default_factory=list, max_length=2)
    cleanup_scope: Literal["process-group", "external"] = "external"
    memory_overhead_mib: int = Field(default=0, ge=0, le=65536)
    process_tree_execution: bool = False


class Heartbeat(Strict):
    description: Description
    reload_ack: int = Field(default=0, ge=0)
    reload_error: str | None = Field(default=None, max_length=256)
    physical_host_id: str | None = Field(default=None, pattern=r'^[0-9a-f]{64}$')
    telemetry: 'HostSample | None' = None


class CPUReading(Strict):
    id: int = Field(ge=0, le=1023)
    percent: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    frequency_mhz: float | None = Field(default=None, ge=0, le=100000, allow_inf_nan=False)


class HostSample(Strict):
    sampled_at: float = Field(ge=0, allow_inf_nan=False)
    source: Literal['linux', 'unavailable']
    cpu_percent: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    cpu_frequency_mhz: float | None = Field(default=None, ge=0, le=100000, allow_inf_nan=False)
    temperature_celsius: float | None = Field(default=None, ge=-100, le=250, allow_inf_nan=False)
    memory_total_mib: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    memory_available_mib: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    disk_total_bytes: int | None = Field(default=None, ge=0)
    disk_available_bytes: int | None = Field(default=None, ge=0)
    throttled: bool | None = None
    cgroup_available: bool = False
    per_cpu: list[CPUReading] = Field(default_factory=list, max_length=1024)


class Completion(Strict):
    state: Literal["succeeded", "failed", "cancelled"]
    result: dict
    module_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    cleanup_ok: bool = True

    @model_validator(mode="after")
    def output_limits(self):
        outputs = self.result.get("outputs", [])
        if not isinstance(outputs, list) or len(outputs) > 32:
            raise ValueError("Result outputs must contain at most 32 files")
        total = 0
        names = set()
        for item in outputs:
            if not isinstance(item, dict): raise ValueError("Invalid output metadata")
            name = str(relative_path(item.get("path")))
            if name in names: raise ValueError("Duplicate output path")
            names.add(name)
            data = item.get("data_base64")
            if not isinstance(data, str) or len(data) > (MAX_OUTPUTS + 2) // 3 * 4:
                raise ValueError("Output exceeds limit")
            content = base64.b64decode(data, validate=True)
            total += len(content)
            if total > MAX_OUTPUTS or item.get("size") != len(content) or item.get("sha256") != hashlib.sha256(content).hexdigest():
                raise ValueError("Invalid output digest, size, or total limit")
        return self


class LogEvent(Strict):
    sequence: int = Field(ge=1, le=1000000)
    stream: Literal['stdout', 'stderr', 'console']
    text: str = Field(max_length=2048)


class LogChunk(Strict):
    events: list[LogEvent] = Field(max_length=64)
    truncated: bool = False
