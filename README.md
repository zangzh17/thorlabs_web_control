# Thorlabs Web Control

Browser-based control for Thorlabs instruments via REST API and real-time streaming.

Currently supported devices:

| Device | Description | Communication |
|--------|-------------|---------------|
| **PM100D** | Optical Power Meter | PyVISA / SCPI over USB |
| **KDC101** | K-Cube DC Servo Motor Controller | FTDI D2XX / APT binary protocol |

## Architecture

Both drivers follow a three-layer design:

```
Browser (HTML/JS)  ←→  FastAPI REST API + SSE  ←→  Service Layer  ←→  Driver
```

- **Driver** — Low-level device communication (SCPI commands for PM100D, APT binary protocol for KDC101)
- **Service** — Thread-safe wrapper with background data acquisition and ring buffer
- **API** — FastAPI endpoints with Server-Sent Events (SSE) for real-time streaming
- **Frontend** — Single-page web UI with live chart (Chart.js), dark theme

## Project Structure

```
thorlabs/
├── pm100d/                     # PM100D Power Meter
│   ├── driver.py               # PyVISA + SCPI driver
│   ├── service.py              # Thread-safe service + power acquisition loop
│   ├── api.py                  # FastAPI REST endpoints + SSE power stream
│   ├── schemas.py              # Pydantic request/response models
│   ├── config.py               # Configuration
│   ├── main.py                 # Entry point (port 8080)
│   └── static/
│       ├── index.html          # Web UI (REST API mode)
│       └── webusb.html         # Web UI (WebUSB direct mode)
│
├── kdc101/                     # KDC101 DC Servo Controller
│   ├── driver.py               # FTDI D2XX + APT protocol driver
│   ├── service.py              # Thread-safe service + position polling loop
│   ├── api.py                  # FastAPI REST endpoints + SSE position stream
│   ├── schemas.py              # Pydantic request/response models
│   ├── config.py               # Configuration
│   ├── main.py                 # Entry point (port 8081)
│   └── static/
│       ├── index.html          # Web UI (REST API mode)
│       └── webserial.html      # Web UI (WebSerial direct mode)
│
├── pyproject.toml              # Dependencies (managed by uv)
└── uv.lock
```

## Quick Start

### Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) package manager
- **PM100D**: NI-VISA or pyvisa-py backend
- **KDC101**: [Thorlabs Kinesis](https://www.thorlabs.com/software_pages/ViewSoftwarePage.cfm?Code=Motion_Control) software installed (provides FTDI D2XX driver)

### Install

```bash
git clone https://github.com/zangzh17/thorlabs_web_control.git
cd thorlabs_web_control
uv sync
```

### Run

```bash
# PM100D Power Meter (port 8080)
uv run python -m uvicorn pm100d.api:app --host 0.0.0.0 --port 8080

# KDC101 DC Servo Controller (port 8081)
uv run python -m uvicorn kdc101.api:app --host 0.0.0.0 --port 8081
```

Open your browser:
- PM100D: http://localhost:8080
- KDC101: http://localhost:8081

### Remote Access

Both servers bind to `0.0.0.0` by default, so any device on the same network can access the web UI via `http://<host-ip>:<port>`.

## PM100D API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/device/list` | List available VISA resources |
| POST | `/device/connect` | Connect to device |
| POST | `/device/disconnect` | Disconnect |
| GET | `/device/info` | Device and sensor information |
| GET | `/device/status` | Connection and acquisition status |
| GET | `/measurement/power` | Single power reading |
| POST | `/measurement/start` | Start continuous acquisition |
| POST | `/measurement/stop` | Stop acquisition |
| GET | `/measurement/buffer?n=100` | Get buffered readings |
| GET | `/measurement/stream` | SSE real-time power stream |
| GET | `/config` | Get all configuration |
| PUT | `/config/wavelength` | Set wavelength (nm) |
| PUT | `/config/range` | Set power range / auto-range |
| PUT | `/config/averaging` | Set averaging count |
| PUT | `/config/unit` | Set unit (W / DBM) |
| POST | `/calibration/zero` | Start zero calibration |
| GET | `/calibration/status` | Check zero status |

## KDC101 API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/device/list` | List available D2XX devices |
| POST | `/device/connect` | Connect by serial number |
| POST | `/device/disconnect` | Disconnect |
| GET | `/device/info` | Hardware info (model, firmware, S/N) |
| POST | `/device/identify` | Flash front panel LED |
| GET | `/device/status` | Position, motion status, limit switches |
| POST | `/motion/home` | Start homing |
| POST | `/motion/move_absolute` | Move to absolute position (mm) |
| POST | `/motion/move_relative` | Move by relative distance (mm) |
| POST | `/motion/jog` | Jog forward or reverse |
| POST | `/motion/stop` | Stop motion (profiled or immediate) |
| POST | `/motion/enable` | Enable motor channel |
| POST | `/motion/disable` | Disable motor channel |
| POST | `/polling/start` | Start position polling |
| POST | `/polling/stop` | Stop polling |
| GET | `/polling/position` | Latest position reading |
| GET | `/polling/buffer?n=100` | Get buffered position readings |
| GET | `/polling/stream` | SSE real-time position stream |
| GET | `/config/velocity` | Get velocity parameters |
| PUT | `/config/velocity` | Set max velocity and acceleration |
| GET | `/config/stage` | Get encoder counts/mm |
| PUT | `/config/stage` | Set encoder counts/mm for your stage |

### Stage Configuration

The KDC101 reports position in encoder counts. The conversion factor depends on your stage:

| Stage | Counts per mm |
|-------|---------------|
| Z812 (default) | 34,555 |
| ZFS13 / ZFS25 | 34,304 |
| MTS25 / MTS50 | 34,304 |
| PRM1-Z8 (rotation) | 1,919.64 counts/deg |

Set via API: `PUT /config/stage` with `{"counts_per_mm": 34304}`

## Browser Direct-Connect Modes

In addition to the REST API mode, each device has a browser-direct page that communicates with the hardware without a backend server:

- **PM100D WebUSB** (`/webusb`) — Uses the WebUSB API to send SCPI commands directly. Requires Chrome/Edge and WinUSB driver (install via [Zadig](https://zadig.akeo.ie/)).

- **KDC101 WebSerial** (`/webserial`) — Uses the WebSerial API to send APT commands directly. Requires Chrome/Edge and FTDI VCP driver (the device must appear as a COM port).

> **Note:** The WebSerial mode for KDC101 requires the FTDI VCP (Virtual COM Port) driver. If you have the Thorlabs Kinesis D2XX driver installed (which is the default), WebSerial will not work — use the REST API mode instead.

## Dependencies

- [FastAPI](https://fastapi.tiangolo.com/) — REST API framework
- [uvicorn](https://www.uvicorn.org/) — ASGI server
- [PyVISA](https://pyvisa.readthedocs.io/) + pyvisa-py — VISA communication (PM100D)
- [ftd2xx](https://github.com/ftd2xx/ftd2xx) — FTDI D2XX driver wrapper (KDC101)
- [pyserial](https://pyserial.readthedocs.io/) — Serial port support
- [sse-starlette](https://github.com/sysid/sse-starlette) — Server-Sent Events
- [Pydantic](https://docs.pydantic.dev/) — Data validation

## License

MIT
