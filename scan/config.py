from pydantic import BaseModel


class ScanAppConfig(BaseModel):
    api_host: str = "0.0.0.0"
    api_port: int = 8082
    default_velocity_mm_s: float = 2.0
    default_acceleration_mm_s2: float = 5.0
    default_sampling_interval_ms: int = 50
