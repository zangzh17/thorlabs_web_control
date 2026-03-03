from pydantic import BaseModel


class PM100DConfig(BaseModel):
    visa_resource: str = ""
    default_wavelength: float = 632.8
    default_averaging: int = 1
    acquisition_interval_ms: int = 100
    buffer_size: int = 10000
    api_host: str = "0.0.0.0"
    api_port: int = 8080
