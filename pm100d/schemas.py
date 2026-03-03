from pydantic import BaseModel


class ConnectRequest(BaseModel):
    visa_resource: str
    timeout_ms: int = 5000


class DeviceInfo(BaseModel):
    idn: str
    sensor_info: str
    wavelength_range: tuple[float, float]
    power_range_limits: tuple[float, float]


class PowerReading(BaseModel):
    timestamp: float
    power: float
    unit: str


class ConfigResponse(BaseModel):
    wavelength: float
    power_range: float
    auto_range: bool
    averaging: int
    power_unit: str
    beam_diameter: float


class WavelengthRequest(BaseModel):
    wavelength_nm: float


class RangeRequest(BaseModel):
    power_range_w: float | None = None
    auto_range: bool | None = None


class AveragingRequest(BaseModel):
    count: int


class UnitRequest(BaseModel):
    unit: str


class AcquisitionRequest(BaseModel):
    interval_ms: int = 100


class StatusResponse(BaseModel):
    connected: bool
    acquiring: bool
    buffer_count: int


class ZeroStatus(BaseModel):
    zeroing: bool
