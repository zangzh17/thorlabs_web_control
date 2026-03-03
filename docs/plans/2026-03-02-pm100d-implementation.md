# PM100D Python Backend Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a pure PyVISA + SCPI driver for Thorlabs PM100D with FastAPI REST API.

**Architecture:** Three layers — synchronous driver (PyVISA/SCPI), thread-safe service (background acquisition + ring buffer), FastAPI REST API with SSE streaming. The driver owns all SCPI communication; the service adds continuous acquisition; the API exposes everything over HTTP.

**Tech Stack:** Python 3.10+, pyvisa, pyvisa-py, fastapi, uvicorn, pydantic

---

### Task 1: Project Scaffold

**Files:**
- Create: `requirements.txt`
- Create: `pm100d/__init__.py`
- Create: `pm100d/config.py`

**Step 1: Create requirements.txt**

```
pyvisa>=1.13
pyvisa-py>=0.7
fastapi>=0.100
uvicorn>=0.23
pydantic>=2.0
sse-starlette>=1.6
```

**Step 2: Create package init**

```python
"""PM100D - Thorlabs PM100D Power Meter Driver & API."""
```

**Step 3: Create config.py**

```python
from pydantic import BaseModel


class PM100DConfig(BaseModel):
    visa_resource: str = ""
    default_wavelength: float = 632.8
    default_averaging: int = 1
    acquisition_interval_ms: int = 100
    buffer_size: int = 10000
    api_host: str = "0.0.0.0"
    api_port: int = 8000
```

**Step 4: Install dependencies**

Run: `pip install -r requirements.txt`

**Step 5: Verify imports**

Run: `python -c "import pyvisa; import fastapi; print('OK')"`
Expected: `OK`

---

### Task 2: Driver — Connection & Device Info

**Files:**
- Create: `pm100d/driver.py`

**Step 1: Implement PM100D driver class with connection and device info**

```python
import pyvisa


class PM100DDriver:
    """Low-level PyVISA + SCPI driver for Thorlabs PM100D."""

    def __init__(self):
        self._rm: pyvisa.ResourceManager | None = None
        self._inst: pyvisa.resources.MessageBasedResource | None = None

    @staticmethod
    def list_devices() -> list[str]:
        rm = pyvisa.ResourceManager()
        resources = rm.list_resources()
        rm.close()
        return list(resources)

    def connect(self, visa_resource: str, timeout_ms: int = 5000) -> None:
        if self._inst is not None:
            self.disconnect()
        self._rm = pyvisa.ResourceManager()
        self._inst = self._rm.open_resource(visa_resource)
        self._inst.timeout = timeout_ms
        self._inst.read_termination = "\n"
        self._inst.write_termination = "\n"

    def disconnect(self) -> None:
        if self._inst is not None:
            self._inst.close()
            self._inst = None
        if self._rm is not None:
            self._rm.close()
            self._rm = None

    @property
    def is_connected(self) -> bool:
        return self._inst is not None

    def _query(self, cmd: str) -> str:
        if self._inst is None:
            raise ConnectionError("PM100D not connected")
        return self._inst.query(cmd).strip()

    def _write(self, cmd: str) -> None:
        if self._inst is None:
            raise ConnectionError("PM100D not connected")
        self._inst.write(cmd)

    # --- Device Info ---

    @property
    def idn(self) -> str:
        return self._query("*IDN?")

    @property
    def sensor_info(self) -> str:
        return self._query("SYST:SENS:IDN?")

    @property
    def wavelength_range(self) -> tuple[float, float]:
        wl_min = float(self._query("SENS:CORR:WAV? MIN"))
        wl_max = float(self._query("SENS:CORR:WAV? MAX"))
        return (wl_min, wl_max)

    @property
    def power_range_limits(self) -> tuple[float, float]:
        p_min = float(self._query("SENS:POW:DC:RANG:UPP? MIN"))
        p_max = float(self._query("SENS:POW:DC:RANG:UPP? MAX"))
        return (p_min, p_max)
```

**Step 2: Verify syntax**

Run: `python -c "from pm100d.driver import PM100DDriver; print('OK')"`
Expected: `OK`

---

### Task 3: Driver — Measurement & Configuration

**Files:**
- Modify: `pm100d/driver.py`

**Step 1: Add measurement methods and configuration properties to PM100DDriver**

Append after the device info section:

```python
    # --- Measurement ---

    def read_power(self) -> float:
        return float(self._query("MEAS:SCAL:POW"))

    def fetch_power(self) -> float:
        return float(self._query("FETC?"))

    def configure_power(self) -> None:
        self._write("CONF:SCAL:POW")

    # --- Configuration ---

    @property
    def wavelength(self) -> float:
        return float(self._query("SENS:CORR:WAV?"))

    @wavelength.setter
    def wavelength(self, nm: float) -> None:
        self._write(f"SENS:CORR:WAV {nm}")

    @property
    def power_range(self) -> float:
        return float(self._query("SENS:POW:DC:RANG:UPP?"))

    @power_range.setter
    def power_range(self, watts: float) -> None:
        self._write(f"SENS:POW:DC:RANG:UPP {watts}")

    @property
    def auto_range(self) -> bool:
        return bool(int(self._query("SENS:POW:DC:RANG:AUTO?")))

    @auto_range.setter
    def auto_range(self, enabled: bool) -> None:
        self._write(f"SENS:POW:DC:RANG:AUTO {int(enabled)}")

    @property
    def averaging(self) -> int:
        return int(self._query("SENS:AVER:COUN?"))

    @averaging.setter
    def averaging(self, count: int) -> None:
        self._write(f"SENS:AVER:COUN {count}")

    @property
    def power_unit(self) -> str:
        return self._query("SENS:POW:DC:UNIT?")

    @power_unit.setter
    def power_unit(self, unit: str) -> None:
        if unit.upper() not in ("W", "DBM"):
            raise ValueError("Unit must be 'W' or 'DBM'")
        self._write(f"SENS:POW:DC:UNIT {unit.upper()}")

    @property
    def beam_diameter(self) -> float:
        return float(self._query("SENS:CORR:BEAM?"))

    @beam_diameter.setter
    def beam_diameter(self, mm: float) -> None:
        self._write(f"SENS:CORR:BEAM {mm}")

    # --- Calibration ---

    def zero_start(self) -> None:
        self._write("SENS:CORR:COLL:ZERO:INIT")

    def zero_abort(self) -> None:
        self._write("SENS:CORR:COLL:ZERO:ABOR")

    @property
    def zero_state(self) -> bool:
        return bool(int(self._query("SENS:CORR:COLL:ZERO:STAT?")))
```

**Step 2: Verify syntax**

Run: `python -c "from pm100d.driver import PM100DDriver; d = PM100DDriver(); print('OK')"`
Expected: `OK`

---

### Task 4: Schemas

**Files:**
- Create: `pm100d/schemas.py`

**Step 1: Create all Pydantic models**

```python
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


class BufferRequest(BaseModel):
    n: int = 100


class StatusResponse(BaseModel):
    connected: bool
    acquiring: bool
    buffer_count: int


class ZeroStatus(BaseModel):
    zeroing: bool
```

**Step 2: Verify syntax**

Run: `python -c "from pm100d.schemas import *; print('OK')"`
Expected: `OK`

---

### Task 5: Service Layer

**Files:**
- Create: `pm100d/service.py`

**Step 1: Implement PM100DService with continuous acquisition**

```python
import threading
import time
from collections import deque

from pm100d.driver import PM100DDriver
from pm100d.schemas import PowerReading


class PM100DService:
    """Thread-safe service layer with background acquisition."""

    def __init__(self, buffer_size: int = 10000):
        self.driver = PM100DDriver()
        self._buffer: deque[PowerReading] = deque(maxlen=buffer_size)
        self._acquiring = False
        self._acq_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    def connect(self, visa_resource: str, timeout_ms: int = 5000) -> None:
        self.driver.connect(visa_resource, timeout_ms)

    def disconnect(self) -> None:
        self.stop_continuous_acquisition()
        self.driver.disconnect()

    @property
    def is_connected(self) -> bool:
        return self.driver.is_connected

    def read_power(self) -> PowerReading:
        power = self.driver.read_power()
        unit = self.driver.power_unit
        return PowerReading(timestamp=time.time(), power=power, unit=unit)

    # --- Continuous Acquisition ---

    def start_continuous_acquisition(self, interval_ms: int = 100) -> None:
        if self._acquiring:
            return
        self._stop_event.clear()
        self._acquiring = True
        self._acq_thread = threading.Thread(
            target=self._acquisition_loop,
            args=(interval_ms / 1000.0,),
            daemon=True,
        )
        self._acq_thread.start()

    def stop_continuous_acquisition(self) -> None:
        if not self._acquiring:
            return
        self._stop_event.set()
        if self._acq_thread is not None:
            self._acq_thread.join(timeout=5.0)
        self._acquiring = False
        self._acq_thread = None

    def _acquisition_loop(self, interval_s: float) -> None:
        while not self._stop_event.is_set():
            try:
                reading = self.read_power()
                with self._lock:
                    self._buffer.append(reading)
            except Exception:
                pass
            self._stop_event.wait(interval_s)

    @property
    def is_acquiring(self) -> bool:
        return self._acquiring

    def get_latest_reading(self) -> PowerReading | None:
        with self._lock:
            return self._buffer[-1] if self._buffer else None

    def get_buffer(self, n: int = 100) -> list[PowerReading]:
        with self._lock:
            items = list(self._buffer)
        return items[-n:]

    @property
    def buffer_count(self) -> int:
        with self._lock:
            return len(self._buffer)

    def clear_buffer(self) -> None:
        with self._lock:
            self._buffer.clear()
```

**Step 2: Verify syntax**

Run: `python -c "from pm100d.service import PM100DService; print('OK')"`
Expected: `OK`

---

### Task 6: FastAPI Endpoints

**Files:**
- Create: `pm100d/api.py`

**Step 1: Implement all REST endpoints**

```python
import asyncio

from fastapi import FastAPI, HTTPException
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
        while True:
            reading = service.get_latest_reading()
            if reading is not None:
                yield {"event": "power", "data": reading.model_dump_json()}
            await asyncio.sleep(0.1)

    return EventSourceResponse(event_generator())


# --- Configuration ---

@app.get("/config")
def config_get() -> ConfigResponse:
    _require_connected()
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
    service.driver.wavelength = req.wavelength_nm
    return {"wavelength_nm": service.driver.wavelength}


@app.put("/config/range")
def config_range(req: RangeRequest) -> dict:
    _require_connected()
    d = service.driver
    if req.auto_range is not None:
        d.auto_range = req.auto_range
    if req.power_range_w is not None:
        d.power_range = req.power_range_w
    return {"power_range": d.power_range, "auto_range": d.auto_range}


@app.put("/config/averaging")
def config_averaging(req: AveragingRequest) -> dict:
    _require_connected()
    service.driver.averaging = req.count
    return {"averaging": service.driver.averaging}


@app.put("/config/unit")
def config_unit(req: UnitRequest) -> dict:
    _require_connected()
    service.driver.power_unit = req.unit
    return {"power_unit": service.driver.power_unit}


# --- Calibration ---

@app.post("/calibration/zero")
def calibration_zero() -> dict:
    _require_connected()
    service.driver.zero_start()
    return {"status": "zeroing"}


@app.get("/calibration/status")
def calibration_status() -> ZeroStatus:
    _require_connected()
    return ZeroStatus(zeroing=service.driver.zero_state)
```

**Step 2: Verify syntax**

Run: `python -c "from pm100d.api import app; print('OK')"`
Expected: `OK`

---

### Task 7: Main Entry Point

**Files:**
- Create: `pm100d/main.py`

**Step 1: Create main.py**

```python
import uvicorn

from pm100d.api import app


def main():
    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
```

**Step 2: Verify the server can start (will exit immediately without device)**

Run: `python -c "from pm100d.main import main; print('Entry point OK')"`
Expected: `Entry point OK`

---

### Task 8: Integration Smoke Test

**Step 1: List VISA devices to verify pyvisa works**

Run: `python -c "from pm100d.driver import PM100DDriver; print(PM100DDriver.list_devices())"`
Expected: List of VISA resources (may be empty if no device connected)

**Step 2: Start API server briefly to confirm endpoints load**

Run: `python -m uvicorn pm100d.api:app --host 127.0.0.1 --port 8000 &; sleep 2; curl http://127.0.0.1/device/status; kill %1`
Expected: JSON response `{"connected": false, "acquiring": false, "buffer_count": 0}`

---
