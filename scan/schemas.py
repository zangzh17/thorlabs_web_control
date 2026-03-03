from typing import Literal

from pydantic import BaseModel


class ScanPoint(BaseModel):
    timestamp: float
    position_mm: float
    power: float
    power_unit: str


class ScanConfig(BaseModel):
    mode: Literal["absolute", "relative"]
    # Absolute mode
    start_mm: float | None = None
    end_mm: float | None = None
    # Relative mode
    distance_mm: float | None = None
    direction: Literal["forward", "backward"] | None = None
    # Common
    velocity_mm_s: float = 2.0
    acceleration_mm_s2: float = 5.0
    sampling_interval_ms: int = 50


class ScanStatus(BaseModel):
    state: Literal["idle", "preparing", "scanning", "complete", "error"]
    progress_percent: float | None = None
    points_collected: int = 0
    error_message: str | None = None
    estimated_time_s: float | None = None


class ScanResult(BaseModel):
    config: ScanConfig
    points: list[ScanPoint]
    start_time: float
    end_time: float
    actual_start_mm: float
    actual_end_mm: float
