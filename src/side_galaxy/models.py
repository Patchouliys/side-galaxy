from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Plan(Strict):
    boards: list[str] = Field(min_length=1, max_length=32)
    template: str = Field(default="cpu-contention", pattern=r"^[a-z0-9-]{1,64}$")
    cpus: list[int] = Field(default=[1], min_length=1, max_length=64)
    interference_cpus: list[int] = Field(default=[2], max_length=64)
    memory_mib: int | None = Field(default=256, ge=128, le=65536)
    duration_seconds: int = Field(default=5, ge=1, le=120)
    bandwidth_percent: int | None = Field(default=None, ge=1, le=100)

    @model_validator(mode="after")
    def unique(self):
        cores = self.cpus + self.interference_cpus
        if len(set(cores)) != len(cores) or any(c < 0 for c in cores):
            raise ValueError("Core sets must be nonnegative, unique and disjoint")
        if len(set(self.boards)) != len(self.boards):
            raise ValueError("Duplicate board IDs")
        return self


class Enrollment(Strict):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[\w .-]+$")
    board_profile: str = Field(default="generic", pattern=r"^[a-z0-9-]{1,64}$")
    system_profile: str = Field(default="simulator", pattern=r"^[a-z0-9-]{1,64}$")


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
    cleanup_scope: Literal["process-group", "external"] = "external"


class Heartbeat(Strict):
    description: Description
    reload_ack: int = Field(default=0, ge=0)
    reload_error: str | None = Field(default=None, max_length=256)


class Completion(Strict):
    state: Literal["succeeded", "failed", "cancelled"]
    result: dict
    module_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    cleanup_ok: bool = True
