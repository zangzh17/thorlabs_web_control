import asyncio
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from pm100d.schemas import (
    AcquisitionRequest,
    ConfigResponse,
    ConnectRequest,
    DeviceInfo,
    PowerReading,
    StatusResponse,
    WavelengthRequest,
    RangeRequest,
    AveragingRequest,
    UnitRequest,
    ZeroStatus,
)
from pm100d.service import PM100DService

app = FastAPI(title="PM100D Power Meter API", version="1.0.0")
service = PM100DService()

_static_dir = Path(__file__).parent / "static"


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(_static_dir / "index.html")


@app.get("/webusb", include_in_schema=False)
def webusb_page():
    return FileResponse(_static_dir / "webusb.html")


def _require_connected():
    if not service.is_connected:
        raise HTTPException(status_code=400, detail="Device not connected")


# --- Device ---


@app.get("/device/list")
def device_list() -> list[str]:
    from pm100d.driver import PM100DDriver

    return PM100DDriver.list_devices()


@app.post("/device/connect")
def device_connect(req: ConnectRequest) -> dict:
    try:
        service.connect(req.visa_resource, req.timeout_ms)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"status": "connected", "resource": req.visa_resource}


@app.post("/device/disconnect")
def device_disconnect() -> dict:
    service.disconnect()
    return {"status": "disconnected"}


@app.get("/device/info")
def device_info() -> DeviceInfo:
    _require_connected()
    with service._driver_lock:
        d = service.driver
        return DeviceInfo(
            idn=d.idn,
            sensor_info=d.sensor_info,
            wavelength_range=d.wavelength_range,
            power_range_limits=d.power_range_limits,
        )


@app.get("/device/status")
def device_status() -> StatusResponse:
    return StatusResponse(
        connected=service.is_connected,
        acquiring=service.is_acquiring,
        buffer_count=service.buffer_count,
    )


# --- Measurement ---


@app.get("/measurement/power")
def measurement_power() -> PowerReading:
    _require_connected()
    return service.read_power()


@app.post("/measurement/start")
def measurement_start(req: AcquisitionRequest = AcquisitionRequest()) -> dict:
    _require_connected()
    service.start_continuous_acquisition(req.interval_ms)
    return {"status": "acquiring", "interval_ms": req.interval_ms}


@app.post("/measurement/stop")
def measurement_stop() -> dict:
    service.stop_continuous_acquisition()
    return {"status": "stopped"}


@app.get("/measurement/buffer")
def measurement_buffer(n: int = 100) -> list[PowerReading]:
    return service.get_buffer(n)


@app.get("/measurement/stream")
async def measurement_stream():
    _require_connected()

    async def event_generator():
        last_ts = 0.0
        while True:
            reading = service.get_latest_reading()
            if reading is not None and reading.timestamp != last_ts:
                last_ts = reading.timestamp
                yield {"event": "power", "data": reading.model_dump_json()}
            await asyncio.sleep(0.05)

    return EventSourceResponse(event_generator())


# --- Configuration ---


@app.get("/config")
def config_get() -> ConfigResponse:
    _require_connected()
    with service._driver_lock:
        d = service.driver
        return ConfigResponse(
            wavelength=d.wavelength,
            power_range=d.power_range,
            auto_range=d.auto_range,
            averaging=d.averaging,
            power_unit=d.power_unit,
            beam_diameter=d.beam_diameter,
        )


@app.put("/config/wavelength")
def config_wavelength(req: WavelengthRequest) -> dict:
    _require_connected()
    with service._driver_lock:
        service.driver.wavelength = req.wavelength_nm
        return {"wavelength_nm": service.driver.wavelength}


@app.put("/config/range")
def config_range(req: RangeRequest) -> dict:
    _require_connected()
    with service._driver_lock:
        d = service.driver
        if req.auto_range is not None:
            d.auto_range = req.auto_range
        if req.power_range_w is not None:
            d.power_range = req.power_range_w
        return {"power_range": d.power_range, "auto_range": d.auto_range}


@app.put("/config/averaging")
def config_averaging(req: AveragingRequest) -> dict:
    _require_connected()
    with service._driver_lock:
        service.driver.averaging = req.count
        return {"averaging": service.driver.averaging}


@app.put("/config/unit")
def config_unit(req: UnitRequest) -> dict:
    _require_connected()
    with service._driver_lock:
        service.driver.power_unit = req.unit
        return {"power_unit": service.driver.power_unit}


# --- Calibration ---


@app.post("/calibration/zero")
def calibration_zero() -> dict:
    _require_connected()
    with service._driver_lock:
        service.driver.zero_start()
    return {"status": "zeroing"}


@app.get("/calibration/status")
def calibration_status() -> ZeroStatus:
    _require_connected()
    with service._driver_lock:
        return ZeroStatus(zeroing=service.driver.zero_state)
