from pydantic import BaseModel


class ConnectRequest(BaseModel):
    serial_number: str


class DeviceInfo(BaseModel):
    serial_number: int
    model: str
    firmware_version: str
    hw_version: int
    num_channels: int


class PositionReading(BaseModel):
    timestamp: float
    position_mm: float
    position_counts: int
    velocity: int
    status_bits: int


class MoveAbsoluteRequest(BaseModel):
    position_mm: float


class MoveRelativeRequest(BaseModel):
    distance_mm: float


class JogRequest(BaseModel):
    direction: str = "forward"  # "forward" or "reverse"


class VelocityParamsRequest(BaseModel):
    max_velocity_mm_s: float
    acceleration_mm_s2: float


class VelocityParamsResponse(BaseModel):
    min_velocity_mm_s: float
    acceleration_mm_s2: float
    max_velocity_mm_s: float


class StageConfigRequest(BaseModel):
    counts_per_mm: float


class PollingRequest(BaseModel):
    interval_ms: int = 100


class StatusResponse(BaseModel):
    connected: bool
    polling: bool
    buffer_count: int
    position_mm: float | None = None
    is_moving: bool = False
    is_homed: bool = False
    is_homing: bool = False
    fwd_limit: bool = False
    rev_limit: bool = False
