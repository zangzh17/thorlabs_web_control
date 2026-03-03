from pydantic import BaseModel


class KDC101Config(BaseModel):
    serial_port: str = ""
    baud_rate: int = 115200
    counts_per_mm: float = 34555  # Z812 stage default
    default_velocity_mm_s: float = 10.0
    default_acceleration_mm_s2: float = 10.0
    polling_interval_ms: int = 100
    buffer_size: int = 10000
    api_host: str = "0.0.0.0"
    api_port: int = 8081
