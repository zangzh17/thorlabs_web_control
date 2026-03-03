# Coordinated Scan Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a unified scan module that coordinates PM100D power meter and KDC101 translation stage for automated spatial power scanning, with a web UI for configuration, real-time visualization, and CSV export.

**Architecture:** New `scan/` module following the project's three-layer pattern (service → API → frontend). Imports PM100D and KDC101 service classes directly (in-process). Runs as a standalone FastAPI app on port 8082.

**Tech Stack:** Python 3.13+, FastAPI, Pydantic, SSE (sse-starlette), Chart.js 4, plain HTML/JS/CSS.

---

### Task 1: Create scan schemas

**Files:**
- Create: `scan/schemas.py`
- Create: `scan/__init__.py`

**Step 1: Create the schemas file**

Create `scan/__init__.py` (empty file).

Create `scan/schemas.py`:

```python
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
```

**Step 2: Commit**

```bash
git add scan/__init__.py scan/schemas.py
git commit -m "feat(scan): add Pydantic schemas for coordinated scan"
```

---

### Task 2: Create scan service

**Files:**
- Create: `scan/service.py`

**Context:** This is the core coordinator. It holds references to PM100DService and KDC101Service, and runs the scan loop in a background thread. The scan loop:
1. Validates both devices connected
2. Sets velocity params on KDC101
3. For absolute mode: moves to start position, waits
4. Starts PM100D acquisition
5. Starts stage motion to end position
6. Polls both for (position, power) pairs at sampling_interval_ms
7. When stage stops moving → stops PM100D acquisition
8. Stores result

**Step 1: Create the service**

Create `scan/service.py`:

```python
import logging
import threading
import time

from pm100d.service import PM100DService
from kdc101.service import KDC101Service
from scan.schemas import ScanConfig, ScanPoint, ScanResult, ScanStatus

logger = logging.getLogger(__name__)


class ScanService:
    """Coordinates PM100D and KDC101 for spatial power scanning."""

    def __init__(
        self,
        pm100d: PM100DService,
        kdc101: KDC101Service,
    ):
        self.pm100d = pm100d
        self.kdc101 = kdc101
        self._points: list[ScanPoint] = []
        self._config: ScanConfig | None = None
        self._state: str = "idle"  # idle, preparing, scanning, complete, error
        self._error_message: str | None = None
        self._scan_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._start_time: float = 0.0
        self._end_time: float = 0.0
        self._actual_start_mm: float = 0.0
        self._actual_end_mm: float = 0.0
        self._target_start_mm: float = 0.0
        self._target_end_mm: float = 0.0

    def get_status(self) -> ScanStatus:
        with self._lock:
            progress = None
            if self._state == "scanning" and self._target_end_mm != self._target_start_mm:
                latest = self.kdc101.get_latest_reading()
                if latest:
                    total = abs(self._target_end_mm - self._target_start_mm)
                    done = abs(latest.position_mm - self._target_start_mm)
                    progress = min(100.0, (done / total) * 100.0) if total > 0 else 0
            return ScanStatus(
                state=self._state,
                progress_percent=progress,
                points_collected=len(self._points),
                error_message=self._error_message,
            )

    def get_points(self) -> list[ScanPoint]:
        with self._lock:
            return list(self._points)

    def get_result(self) -> ScanResult | None:
        with self._lock:
            if self._state != "complete" or self._config is None:
                return None
            return ScanResult(
                config=self._config,
                points=list(self._points),
                start_time=self._start_time,
                end_time=self._end_time,
                actual_start_mm=self._actual_start_mm,
                actual_end_mm=self._actual_end_mm,
            )

    def estimate_time(self, config: ScanConfig) -> float:
        """Estimate scan time in seconds (trapezoidal profile approximation)."""
        if config.mode == "absolute":
            distance = abs(config.end_mm - config.start_mm)
        else:
            distance = config.distance_mm or 0
        v = config.velocity_mm_s
        a = config.acceleration_mm_s2
        # Time to accelerate to max velocity
        t_accel = v / a
        d_accel = 0.5 * a * t_accel**2
        if 2 * d_accel >= distance:
            # Triangle profile (never reaches max velocity)
            return 2 * (distance / a) ** 0.5
        else:
            # Trapezoidal profile
            d_cruise = distance - 2 * d_accel
            t_cruise = d_cruise / v
            return 2 * t_accel + t_cruise

    def start_scan(self, config: ScanConfig) -> None:
        if self._state == "scanning" or self._state == "preparing":
            raise RuntimeError("Scan already in progress")
        if not self.pm100d.is_connected:
            raise RuntimeError("PM100D not connected")
        if not self.kdc101.is_connected:
            raise RuntimeError("KDC101 not connected")

        with self._lock:
            self._config = config
            self._points = []
            self._state = "preparing"
            self._error_message = None
            self._stop_event.clear()

        self._scan_thread = threading.Thread(target=self._scan_loop, daemon=True)
        self._scan_thread.start()

    def stop_scan(self) -> None:
        self._stop_event.set()
        self.kdc101.stop(immediate=False)

    def _scan_loop(self) -> None:
        config = self._config
        try:
            # Set velocity parameters
            self.kdc101.set_velocity_params(config.velocity_mm_s, config.acceleration_mm_s2)
            time.sleep(0.1)

            # Determine start and end positions
            if config.mode == "absolute":
                start_mm = config.start_mm
                end_mm = config.end_mm
            else:
                # Relative mode: get current position
                status = self.kdc101.get_status()
                current = status["position_mm"]
                dist = config.distance_mm
                if config.direction == "backward":
                    dist = -dist
                start_mm = current
                end_mm = current + dist

            self._target_start_mm = start_mm
            self._target_end_mm = end_mm

            # For absolute mode, move to start position first
            if config.mode == "absolute":
                logger.info("Moving to start position: %.3f mm", start_mm)
                self.kdc101.move_absolute(start_mm)
                # Wait for stage to arrive at start
                if not self._wait_for_stop(timeout=60):
                    return

            if self._stop_event.is_set():
                with self._lock:
                    self._state = "idle"
                return

            # Record actual start
            status = self.kdc101.get_status()
            self._actual_start_mm = status["position_mm"]

            # Start PM100D acquisition
            self.pm100d.clear_buffer()
            self.pm100d.start_continuous_acquisition(interval_ms=config.sampling_interval_ms)

            # Start KDC101 polling
            self.kdc101.clear_buffer()
            self.kdc101.start_polling(interval_ms=config.sampling_interval_ms)

            # Small delay to let first readings come in
            time.sleep(config.sampling_interval_ms / 1000.0 * 2)

            # Begin motion
            with self._lock:
                self._state = "scanning"
                self._start_time = time.time()

            logger.info("Starting scan motion to %.3f mm", end_mm)
            if config.mode == "absolute":
                self.kdc101.move_absolute(end_mm)
            else:
                self.kdc101.move_relative(config.distance_mm if config.direction == "forward" else -config.distance_mm)

            # Collection loop
            interval_s = config.sampling_interval_ms / 1000.0
            while not self._stop_event.is_set():
                # Read latest from both
                pos_reading = self.kdc101.get_latest_reading()
                pwr_reading = self.pm100d.get_latest_reading()

                if pos_reading and pwr_reading:
                    point = ScanPoint(
                        timestamp=time.time(),
                        position_mm=pos_reading.position_mm,
                        power=pwr_reading.power,
                        power_unit=pwr_reading.unit,
                    )
                    with self._lock:
                        self._points.append(point)

                # Check if stage has stopped moving
                last_status = self.kdc101.last_status
                if last_status and not last_status["is_moving"]:
                    # Collect a few more points after stop
                    time.sleep(interval_s * 3)
                    for _ in range(3):
                        pos_reading = self.kdc101.get_latest_reading()
                        pwr_reading = self.pm100d.get_latest_reading()
                        if pos_reading and pwr_reading:
                            point = ScanPoint(
                                timestamp=time.time(),
                                position_mm=pos_reading.position_mm,
                                power=pwr_reading.power,
                                power_unit=pwr_reading.unit,
                            )
                            with self._lock:
                                self._points.append(point)
                        time.sleep(interval_s)
                    break

                time.sleep(interval_s)

            # Stop acquisition and polling
            self.pm100d.stop_continuous_acquisition()
            self.kdc101.stop_polling()

            # Record end
            status = self.kdc101.get_status()
            self._actual_end_mm = status["position_mm"]

            with self._lock:
                self._end_time = time.time()
                self._state = "complete"

            logger.info(
                "Scan complete: %d points, %.1fs",
                len(self._points),
                self._end_time - self._start_time,
            )

        except Exception as e:
            logger.exception("Scan failed")
            with self._lock:
                self._state = "error"
                self._error_message = str(e)
            # Try to clean up
            try:
                self.pm100d.stop_continuous_acquisition()
            except Exception:
                pass
            try:
                self.kdc101.stop_polling()
            except Exception:
                pass

    def _wait_for_stop(self, timeout: float = 60) -> bool:
        """Wait for stage to stop moving. Returns False if aborted or timed out."""
        deadline = time.time() + timeout
        time.sleep(0.3)  # Let motion start
        while time.time() < deadline:
            if self._stop_event.is_set():
                with self._lock:
                    self._state = "idle"
                return False
            status = self.kdc101.get_status()
            if not status["is_moving"]:
                return True
            time.sleep(0.1)
        with self._lock:
            self._state = "error"
            self._error_message = "Timeout waiting for stage"
        return False
```

**Step 2: Commit**

```bash
git add scan/service.py
git commit -m "feat(scan): add scan service with coordinated acquisition logic"
```

---

### Task 3: Create scan API

**Files:**
- Create: `scan/api.py`

**Context:** FastAPI app that exposes scan endpoints + proxies device management to the underlying services. Uses SSE to stream scan points in real-time. Also serves the static frontend.

**Step 1: Create the API**

Create `scan/api.py`:

```python
import asyncio
import csv
import io
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from pm100d.driver import PM100DDriver
from pm100d.service import PM100DService
from pm100d.schemas import (
    AcquisitionRequest,
    AveragingRequest,
    ConfigResponse,
    ConnectRequest as PM100DConnectRequest,
    DeviceInfo as PM100DDeviceInfo,
    PowerReading,
    RangeRequest,
    StatusResponse as PM100DStatusResponse,
    UnitRequest,
    WavelengthRequest,
    ZeroStatus,
)

from kdc101.driver import KDC101Driver
from kdc101.service import KDC101Service
from kdc101.schemas import (
    ConnectRequest as KDC101ConnectRequest,
    DeviceInfo as KDC101DeviceInfo,
    MoveAbsoluteRequest,
    MoveRelativeRequest,
    StageConfigRequest,
    StatusResponse as KDC101StatusResponse,
    VelocityParamsRequest,
    VelocityParamsResponse,
)

from scan.schemas import ScanConfig, ScanPoint, ScanResult, ScanStatus
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
                # Send new points
                for p in points[last_count:]:
                    yield {"event": "scan_point", "data": p.model_dump_json()}
                last_count = len(points)
            # Send status updates
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
```

**Step 2: Commit**

```bash
git add scan/api.py
git commit -m "feat(scan): add FastAPI endpoints with SSE streaming and CSV export"
```

---

### Task 4: Create scan config and main entry point

**Files:**
- Create: `scan/config.py`
- Create: `scan/main.py`

**Step 1: Create config and main**

Create `scan/config.py`:

```python
from pydantic import BaseModel


class ScanAppConfig(BaseModel):
    api_host: str = "0.0.0.0"
    api_port: int = 8082
    default_velocity_mm_s: float = 2.0
    default_acceleration_mm_s2: float = 5.0
    default_sampling_interval_ms: int = 50
```

Create `scan/main.py`:

```python
import uvicorn

from scan.api import app


def main():
    uvicorn.run(app, host="0.0.0.0", port=8082)


if __name__ == "__main__":
    main()
```

**Step 2: Commit**

```bash
git add scan/config.py scan/main.py
git commit -m "feat(scan): add config and entry point (port 8082)"
```

---

### Task 5: Create the frontend HTML page

**Files:**
- Create: `scan/static/index.html`

**Context:** This is the main deliverable UI. Dark theme matching existing pages. Layout: sidebar (320px) with device setup, PM100D config, stage config, scan setup panels. Main area with Chart.js scatter plot (power vs position), dual-handle range slider, export buttons. All text in English.

The frontend uses the same CSS patterns as `pm100d/static/index.html` (dark theme, `.panel`, `.btn-*`, `.field` classes). It communicates with the API at the same origin.

**Step 1: Create the static directory and HTML file**

```bash
mkdir -p scan/static
```

Create `scan/static/index.html` — this is a large file. Key sections:

1. **HTML structure**: Header with title + status dots for both devices. Grid layout with sidebar + main area.

2. **Sidebar panels**:
   - Device Setup: dropdowns + connect/disconnect for PM100D and KDC101
   - PM100D Config: wavelength, power range, auto range toggle, averaging, unit select
   - Stage Config: velocity, acceleration, home button, current position display
   - Scan Setup: mode radio (Absolute/Relative), conditional fields, sampling interval, estimated time, start/stop buttons
   - Log panel

3. **Main area**:
   - Chart.js scatter chart (X=position mm, Y=power)
   - Range selector with two input[type=range] sliders
   - Export buttons (Export All CSV, Export Range CSV) with point counts

4. **JavaScript**:
   - API calls using fetch()
   - SSE listener for `/scan/stream`
   - Chart.js real-time updates
   - Range slider logic
   - Time estimation (calls `/scan/estimate`)
   - CSV download via `/scan/export`

The complete HTML file (see implementation below) follows the exact styling from the existing PM100D page.

**Step 2: Commit**

```bash
git add scan/static/index.html
git commit -m "feat(scan): add frontend UI with real-time chart and CSV export"
```

---

### Task 6: Integration testing and final touches

**Step 1: Verify the module structure**

```bash
ls -la scan/
# Expected:
# __init__.py
# api.py
# config.py
# main.py
# schemas.py
# service.py
# static/
#   index.html
```

**Step 2: Test that the server starts**

```bash
cd D:/Zihan/code/thorlabs_web_control
python -m scan.main
# Expected: Uvicorn running on http://0.0.0.0:8082
# Visit http://localhost:8082 and verify the UI loads
```

**Step 3: Verify API docs load**

Visit `http://localhost:8082/docs` — should show all endpoints.

**Step 4: Final commit**

```bash
git add -A
git commit -m "feat(scan): coordinated scan module complete"
```

---

## File Summary

| File | Purpose |
|------|---------|
| `scan/__init__.py` | Package marker |
| `scan/schemas.py` | Pydantic models: ScanPoint, ScanConfig, ScanStatus, ScanResult |
| `scan/service.py` | Core scan coordinator, background thread, device orchestration |
| `scan/api.py` | FastAPI endpoints + SSE + CSV export + device proxy endpoints |
| `scan/config.py` | Default configuration |
| `scan/main.py` | Entry point (port 8082) |
| `scan/static/index.html` | Full web UI with Chart.js, range slider, CSV export |

## Running

```bash
# Start the coordinated scan service (includes both devices)
python -m scan.main

# Open browser to http://localhost:8082
# Connect both devices, configure, and run scan
```
