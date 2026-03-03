import asyncio
import csv
import io
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from sse_starlette.sse import EventSourceResponse

from pm100d.driver import PM100DDriver
from pm100d.service import PM100DService
from pm100d.schemas import (
    AveragingRequest,
    ConfigResponse,
    ConnectRequest as PM100DConnectRequest,
    RangeRequest,
    StatusResponse as PM100DStatusResponse,
    UnitRequest,
    WavelengthRequest,
)

from kdc101.driver import KDC101Driver
from kdc101.service import KDC101Service
from kdc101.schemas import (
    ConnectRequest as KDC101ConnectRequest,
    MoveAbsoluteRequest,
    StageConfigRequest,
    StatusResponse as KDC101StatusResponse,
    VelocityParamsRequest,
    VelocityParamsResponse,
)

from scan.schemas import ScanConfig, ScanResult, ScanStatus
from scan.service import ScanService

app = FastAPI(title="Coordinated Scan API", version="1.0.0")

# Shared service instances
pm100d_service = PM100DService()
kdc101_service = KDC101Service()
scan_service = ScanService(pm100d_service, kdc101_service)

_static_dir = Path(__file__).parent / "static"


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(_static_dir / "index.html")


# ─── Scan Endpoints ──────────────────────────────────────────────────────────


@app.post("/scan/start")
def scan_start(config: ScanConfig) -> dict:
    try:
        scan_service.start_scan(config)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "started", "estimated_time_s": scan_service.estimate_time(config)}


@app.post("/scan/stop")
def scan_stop() -> dict:
    scan_service.stop_scan()
    return {"status": "stopping"}


@app.get("/scan/status")
def scan_status() -> ScanStatus:
    return scan_service.get_status()


@app.get("/scan/result")
def scan_result() -> ScanResult:
    result = scan_service.get_result()
    if result is None:
        raise HTTPException(status_code=404, detail="No completed scan result")
    return result


@app.post("/scan/estimate")
def scan_estimate(config: ScanConfig) -> dict:
    return {"estimated_time_s": scan_service.estimate_time(config)}


@app.get("/scan/stream")
async def scan_stream():
    last_count = 0

    async def event_generator():
        nonlocal last_count
        while True:
            status = scan_service.get_status()
            points = scan_service.get_points()
            if len(points) > last_count:
                for p in points[last_count:]:
                    yield {"event": "scan_point", "data": p.model_dump_json()}
                last_count = len(points)
            yield {"event": "scan_status", "data": status.model_dump_json()}
            if status.state in ("complete", "error", "idle"):
                break
            await asyncio.sleep(0.05)

    return EventSourceResponse(event_generator())


@app.get("/scan/export")
def scan_export(
    start_mm: float | None = Query(None),
    end_mm: float | None = Query(None),
) -> StreamingResponse:
    result = scan_service.get_result()
    if result is None:
        raise HTTPException(status_code=404, detail="No completed scan result")

    points = result.points
    if start_mm is not None and end_mm is not None:
        lo, hi = min(start_mm, end_mm), max(start_mm, end_mm)
        points = [p for p in points if lo <= p.position_mm <= hi]

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["timestamp", "position_mm", "power", "power_unit"])
    for p in points:
        writer.writerow([p.timestamp, p.position_mm, p.power, p.power_unit])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=scan_data.csv"},
    )


# ─── PM100D Proxy Endpoints ─────────────────────────────────────────────────

def _require_pm100d():
    if not pm100d_service.is_connected:
        raise HTTPException(status_code=400, detail="PM100D not connected")


@app.get("/pm100d/device/list")
def pm100d_device_list() -> list[str]:
    return PM100DDriver.list_devices()


@app.post("/pm100d/device/connect")
def pm100d_device_connect(req: PM100DConnectRequest) -> dict:
    try:
        pm100d_service.connect(req.visa_resource, req.timeout_ms)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"status": "connected", "resource": req.visa_resource}


@app.post("/pm100d/device/disconnect")
def pm100d_device_disconnect() -> dict:
    pm100d_service.disconnect()
    return {"status": "disconnected"}


@app.get("/pm100d/device/status")
def pm100d_device_status() -> PM100DStatusResponse:
    return PM100DStatusResponse(
        connected=pm100d_service.is_connected,
        acquiring=pm100d_service.is_acquiring,
        buffer_count=pm100d_service.buffer_count,
    )


@app.get("/pm100d/config")
def pm100d_config_get() -> ConfigResponse:
    _require_pm100d()
    with pm100d_service._driver_lock:
        d = pm100d_service.driver
        return ConfigResponse(
            wavelength=d.wavelength,
            power_range=d.power_range,
            auto_range=d.auto_range,
            averaging=d.averaging,
            power_unit=d.power_unit,
            beam_diameter=d.beam_diameter,
        )


@app.put("/pm100d/config/wavelength")
def pm100d_config_wavelength(req: WavelengthRequest) -> dict:
    _require_pm100d()
    with pm100d_service._driver_lock:
        pm100d_service.driver.wavelength = req.wavelength_nm
        return {"wavelength_nm": pm100d_service.driver.wavelength}


@app.put("/pm100d/config/range")
def pm100d_config_range(req: RangeRequest) -> dict:
    _require_pm100d()
    with pm100d_service._driver_lock:
        d = pm100d_service.driver
        if req.auto_range is not None:
            d.auto_range = req.auto_range
        if req.power_range_w is not None:
            d.power_range = req.power_range_w
        return {"power_range": d.power_range, "auto_range": d.auto_range}


@app.put("/pm100d/config/averaging")
def pm100d_config_averaging(req: AveragingRequest) -> dict:
    _require_pm100d()
    with pm100d_service._driver_lock:
        pm100d_service.driver.averaging = req.count
        return {"averaging": pm100d_service.driver.averaging}


@app.put("/pm100d/config/unit")
def pm100d_config_unit(req: UnitRequest) -> dict:
    _require_pm100d()
    with pm100d_service._driver_lock:
        pm100d_service.driver.power_unit = req.unit
        return {"power_unit": pm100d_service.driver.power_unit}


@app.post("/pm100d/calibration/zero")
def pm100d_calibration_zero() -> dict:
    _require_pm100d()
    with pm100d_service._driver_lock:
        pm100d_service.driver.zero_start()
    return {"status": "zeroing"}


# ─── KDC101 Proxy Endpoints ─────────────────────────────────────────────────

def _require_kdc101():
    if not kdc101_service.is_connected:
        raise HTTPException(status_code=400, detail="KDC101 not connected")


@app.get("/kdc101/device/list")
def kdc101_device_list() -> list[dict]:
    return KDC101Driver.list_devices()


@app.post("/kdc101/device/connect")
def kdc101_device_connect(req: KDC101ConnectRequest) -> dict:
    try:
        kdc101_service.connect(req.serial_number)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"status": "connected", "serial_number": req.serial_number}


@app.post("/kdc101/device/disconnect")
def kdc101_device_disconnect() -> dict:
    kdc101_service.disconnect()
    return {"status": "disconnected"}


@app.get("/kdc101/device/status")
def kdc101_device_status() -> KDC101StatusResponse:
    resp = KDC101StatusResponse(
        connected=kdc101_service.is_connected,
        polling=kdc101_service.is_polling,
        buffer_count=kdc101_service.buffer_count,
    )
    if kdc101_service.is_connected:
        last = kdc101_service.last_status
        if last:
            resp.position_mm = last["position_mm"]
            resp.is_moving = last["is_moving"]
            resp.is_homed = last["is_homed"]
            resp.is_homing = last["is_homing"]
            resp.fwd_limit = last["fwd_limit"]
            resp.rev_limit = last["rev_limit"]
    return resp


@app.post("/kdc101/motion/home")
def kdc101_motion_home() -> dict:
    _require_kdc101()
    kdc101_service.home()
    return {"status": "homing"}


@app.post("/kdc101/motion/stop")
def kdc101_motion_stop(immediate: bool = False) -> dict:
    _require_kdc101()
    kdc101_service.stop(immediate)
    return {"status": "stopped"}


@app.post("/kdc101/motion/move_absolute")
def kdc101_motion_move_absolute(req: MoveAbsoluteRequest) -> dict:
    _require_kdc101()
    kdc101_service.move_absolute(req.position_mm)
    return {"status": "moving", "target_mm": req.position_mm}


@app.get("/kdc101/config/velocity")
def kdc101_config_velocity_get() -> VelocityParamsResponse:
    _require_kdc101()
    params = kdc101_service.get_velocity_params()
    return VelocityParamsResponse(**params)


@app.put("/kdc101/config/velocity")
def kdc101_config_velocity_set(req: VelocityParamsRequest) -> dict:
    _require_kdc101()
    kdc101_service.set_velocity_params(req.max_velocity_mm_s, req.acceleration_mm_s2)
    return {"status": "ok", **req.model_dump()}


@app.get("/kdc101/config/stage")
def kdc101_config_stage_get() -> dict:
    return {"counts_per_mm": kdc101_service.counts_per_mm}


@app.put("/kdc101/config/stage")
def kdc101_config_stage_set(req: StageConfigRequest) -> dict:
    kdc101_service.counts_per_mm = req.counts_per_mm
    return {"counts_per_mm": kdc101_service.counts_per_mm}
