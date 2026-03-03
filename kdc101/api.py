import asyncio
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from sse_starlette.sse import EventSourceResponse

from kdc101.schemas import (
    ConnectRequest,
    DeviceInfo,
    JogRequest,
    MoveAbsoluteRequest,
    MoveRelativeRequest,
    PollingRequest,
    PositionReading,
    StageConfigRequest,
    StatusResponse,
    VelocityParamsRequest,
    VelocityParamsResponse,
)
from kdc101.service import KDC101Service

app = FastAPI(title="KDC101 DC Servo Controller API", version="1.0.0")
service = KDC101Service()

_static_dir = Path(__file__).parent / "static"


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(_static_dir / "index.html")


@app.get("/webserial", include_in_schema=False)
def webserial_page():
    return FileResponse(_static_dir / "webserial.html")


def _require_connected():
    if not service.is_connected:
        raise HTTPException(status_code=400, detail="Device not connected")


# --- Device --------------------------------------------------------------


@app.get("/device/list")
def device_list() -> list[dict]:
    from kdc101.driver import KDC101Driver

    return KDC101Driver.list_devices()


@app.post("/device/connect")
def device_connect(req: ConnectRequest) -> dict:
    try:
        service.connect(req.serial_number)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"status": "connected", "serial_number": req.serial_number}


@app.post("/device/disconnect")
def device_disconnect() -> dict:
    service.disconnect()
    return {"status": "disconnected"}


@app.get("/device/info")
def device_info() -> DeviceInfo:
    _require_connected()
    try:
        info = service.get_hw_info()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return DeviceInfo(**info)


@app.post("/device/identify")
def device_identify() -> dict:
    _require_connected()
    service.identify()
    return {"status": "ok"}


@app.get("/device/status")
def device_status() -> StatusResponse:
    resp = StatusResponse(
        connected=service.is_connected,
        polling=service.is_polling,
        buffer_count=service.buffer_count,
    )
    if service.is_connected:
        last = service.last_status
        if last:
            resp.position_mm = last["position_mm"]
            resp.is_moving = last["is_moving"]
            resp.is_homed = last["is_homed"]
            resp.is_homing = last["is_homing"]
            resp.fwd_limit = last["fwd_limit"]
            resp.rev_limit = last["rev_limit"]
    return resp


# --- Motion --------------------------------------------------------------


@app.post("/motion/home")
def motion_home() -> dict:
    _require_connected()
    service.home()
    return {"status": "homing"}


@app.post("/motion/move_absolute")
def motion_move_absolute(req: MoveAbsoluteRequest) -> dict:
    _require_connected()
    service.move_absolute(req.position_mm)
    return {"status": "moving", "target_mm": req.position_mm}


@app.post("/motion/move_relative")
def motion_move_relative(req: MoveRelativeRequest) -> dict:
    _require_connected()
    service.move_relative(req.distance_mm)
    return {"status": "moving", "distance_mm": req.distance_mm}


@app.post("/motion/jog")
def motion_jog(req: JogRequest = JogRequest()) -> dict:
    _require_connected()
    direction = 1 if req.direction == "forward" else 2
    service.jog(direction)
    return {"status": "jogging", "direction": req.direction}


@app.post("/motion/stop")
def motion_stop(immediate: bool = False) -> dict:
    _require_connected()
    service.stop(immediate)
    return {"status": "stopped"}


@app.post("/motion/enable")
def motion_enable() -> dict:
    _require_connected()
    service.enable()
    return {"status": "enabled"}


@app.post("/motion/disable")
def motion_disable() -> dict:
    _require_connected()
    service.disable()
    return {"status": "disabled"}


# --- Position polling & streaming ----------------------------------------


@app.post("/polling/start")
def polling_start(req: PollingRequest = PollingRequest()) -> dict:
    _require_connected()
    service.start_polling(req.interval_ms)
    return {"status": "polling", "interval_ms": req.interval_ms}


@app.post("/polling/stop")
def polling_stop() -> dict:
    service.stop_polling()
    return {"status": "stopped"}


@app.get("/polling/position")
def polling_position() -> PositionReading | None:
    reading = service.get_latest_reading()
    if reading is None:
        raise HTTPException(status_code=404, detail="No position data available")
    return reading


@app.get("/polling/buffer")
def polling_buffer(n: int = 100) -> list[PositionReading]:
    return service.get_buffer(n)


@app.get("/polling/stream")
async def polling_stream():
    _require_connected()

    async def event_generator():
        last_ts = 0.0
        while True:
            reading = service.get_latest_reading()
            if reading is not None and reading.timestamp != last_ts:
                last_ts = reading.timestamp
                yield {"event": "position", "data": reading.model_dump_json()}
            await asyncio.sleep(0.05)

    return EventSourceResponse(event_generator())


# --- Configuration -------------------------------------------------------


@app.get("/config/velocity")
def config_velocity_get() -> VelocityParamsResponse:
    _require_connected()
    params = service.get_velocity_params()
    return VelocityParamsResponse(**params)


@app.put("/config/velocity")
def config_velocity_set(req: VelocityParamsRequest) -> dict:
    _require_connected()
    service.set_velocity_params(req.max_velocity_mm_s, req.acceleration_mm_s2)
    return {"status": "ok", **req.model_dump()}


@app.get("/config/stage")
def config_stage_get() -> dict:
    return {"counts_per_mm": service.counts_per_mm}


@app.put("/config/stage")
def config_stage_set(req: StageConfigRequest) -> dict:
    service.counts_per_mm = req.counts_per_mm
    return {"counts_per_mm": service.counts_per_mm}
