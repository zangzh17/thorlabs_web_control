# PM100D Python Backend Design

## Overview

Pure PyVISA + SCPI driver for Thorlabs PM100D power meter, with FastAPI REST API layer.

## Architecture

Three-layer design:

```
driver.py   -> PyVISA + SCPI (synchronous)
service.py  -> Business logic, continuous acquisition (background thread)
api.py      -> FastAPI REST endpoints + SSE streaming
```

## Layer 1: Driver (`driver.py`)

Synchronous PyVISA wrapper. All SCPI commands for power measurement mode.

### Connection
- `connect(visa_resource: str)` - Open VISA resource
- `disconnect()` - Close connection
- `is_connected -> bool`
- `list_devices() -> list[str]` - Static method, list VISA resources

### Measurement
- `read_power() -> float` - `MEAS:SCAL:POW`
- `fetch_power() -> float` - `FETC`

### Configuration
- `wavelength -> float` (get/set) - `SENS:CORR:WAV`
- `power_range -> float` (get/set) - `SENS:POW:DC:RANG:UPP`
- `auto_range -> bool` (get/set) - `SENS:POW:DC:RANG:AUTO`
- `averaging -> int` (get/set) - `SENS:AVER:COUN`
- `power_unit -> str` (get/set) - `SENS:POW:DC:UNIT` (W/dBm)
- `beam_diameter -> float` (get/set) - `SENS:CORR:BEAM`

### Calibration
- `zero_start()` - `SENS:CORR:COLL:ZERO:INIT`
- `zero_abort()` - `SENS:CORR:COLL:ZERO:ABOR`
- `zero_state -> bool` - `SENS:CORR:COLL:ZERO:STAT`

### Device Info
- `idn -> str` - `*IDN?`
- `sensor_info -> str` - `SYST:SENS:IDN`
- `wavelength_range -> tuple[float, float]` - `SENS:CORR:WAV MIN/MAX`
- `power_range_limits -> tuple[float, float]` - `SENS:POW:DC:RANG:UPP MIN/MAX`

## Layer 2: Service (`service.py`)

Thread-safe business logic with background acquisition.

- `start_continuous_acquisition(interval_ms: int)` - Spawns background thread
- `stop_continuous_acquisition()`
- `get_latest_reading() -> PowerReading`
- `get_buffer(n: int) -> list[PowerReading]` - Ring buffer of recent readings
- `is_acquiring -> bool`

Data model:
```python
class PowerReading:
    timestamp: float
    power: float
    unit: str
```

## Layer 3: API (`api.py`)

FastAPI REST endpoints.

### Device
- `GET /device/info` - Device and sensor info
- `POST /device/connect` - Connect by VISA resource string
- `POST /device/disconnect`
- `GET /device/list` - Available VISA resources

### Measurement
- `GET /measurement/power` - Single power reading
- `POST /measurement/start` - Start continuous acquisition
- `POST /measurement/stop` - Stop continuous acquisition
- `GET /measurement/buffer` - Buffered readings
- `GET /measurement/stream` - SSE real-time stream

### Configuration
- `GET /config` - All current settings
- `PUT /config/wavelength`
- `PUT /config/range`
- `PUT /config/averaging`
- `PUT /config/unit`

### Calibration
- `POST /calibration/zero` - Start zero adjustment
- `GET /calibration/status`

## Dependencies

- `pyvisa` - VISA communication
- `pyvisa-py` - Pure Python VISA backend (no NI-VISA needed)
- `fastapi` - Web framework
- `uvicorn` - ASGI server
- `pydantic` - Data validation

## File Structure

```
pm100d/
├── __init__.py
├── driver.py
├── service.py
├── api.py
├── schemas.py
├── config.py
└── main.py
requirements.txt
```
