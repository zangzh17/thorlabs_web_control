# Coordinated Scan — Design Document

**Date**: 2026-03-03
**Status**: Approved

## Overview

A new `scan/` module that coordinates PM100D power meter and KDC101 translation stage for automated spatial power scanning. The stage moves through a range while the power meter records measurements, producing a power-vs-position dataset.

## Architecture

### Module Structure

```
scan/
├── service.py      # Scan coordinator (imports pm100d + kdc101 services)
├── api.py          # FastAPI endpoints + SSE streaming
├── schemas.py      # Pydantic models
├── config.py       # Default configuration
├── main.py         # Entry point (port 8082)
└── static/
    └── index.html  # Unified scan UI
```

### Integration Pattern

- Direct import of `pm100d.service.PM100DService` and `kdc101.service.KDC101Service`
- Single process, single FastAPI app
- Existing PM100D and KDC101 modules remain independently runnable

## Backend Design

### Scan Flow

1. User configures scan parameters and clicks Start
2. Backend validates both devices are connected
3. Sets KDC101 velocity/acceleration params
4. **Absolute mode**: moves stage to start position, waits for arrival
5. **Relative mode**: calculates end position from current + direction * distance
6. Starts PM100D continuous acquisition
7. Starts stage motion to end position
8. Background thread polls both services, collecting `ScanPoint(timestamp, position_mm, power, power_unit)` pairs
9. Streams points via SSE to frontend
10. When stage stops moving → stops PM100D acquisition
11. Stores complete dataset for retrieval/export

### Scan Modes

| Mode | Parameters | Behavior |
|------|-----------|----------|
| **Absolute** | start_mm, end_mm | Move to start, scan to end |
| **Relative** | distance_mm, direction (+/-) | Start = current pos, end = current ± distance |

### Time Estimation

```
estimated_time ≈ distance / velocity + velocity / acceleration
```

Trapezoidal motion profile approximation, displayed to user before starting.

### Data Models

```python
class ScanPoint(BaseModel):
    timestamp: float
    position_mm: float
    power: float
    power_unit: str

class ScanConfig(BaseModel):
    mode: Literal["absolute", "relative"]
    start_mm: float | None = None       # absolute mode
    end_mm: float | None = None         # absolute mode
    distance_mm: float | None = None    # relative mode
    direction: Literal["forward", "backward"] | None = None  # relative mode
    velocity_mm_s: float = 2.0
    acceleration_mm_s2: float = 5.0
    sampling_interval_ms: int = 50

class ScanResult(BaseModel):
    config: ScanConfig
    points: list[ScanPoint]
    start_time: float
    end_time: float
    actual_start_mm: float
    actual_end_mm: float

class ScanStatus(BaseModel):
    state: Literal["idle", "preparing", "scanning", "complete", "error"]
    progress_percent: float | None = None
    points_collected: int = 0
    error_message: str | None = None
```

### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/scan/start` | Start scan with ScanConfig body |
| POST | `/scan/stop` | Abort running scan |
| GET | `/scan/status` | Current scan state, progress |
| GET | `/scan/result` | Complete scan data (after scan) |
| GET | `/scan/stream` | SSE stream of live ScanPoints |
| GET | `/scan/export` | CSV download, optional `start_mm` & `end_mm` query params |

Device management endpoints (proxied to underlying services):

| Method | Path | Description |
|--------|------|-------------|
| GET | `/pm100d/device/list` | List VISA resources |
| POST | `/pm100d/device/connect` | Connect PM100D |
| POST | `/pm100d/device/disconnect` | Disconnect PM100D |
| GET | `/pm100d/device/status` | PM100D status |
| GET | `/pm100d/config` | PM100D config |
| PUT | `/pm100d/config/wavelength` | Set wavelength |
| PUT | `/pm100d/config/range` | Set power range |
| PUT | `/pm100d/config/averaging` | Set averaging |
| PUT | `/pm100d/config/unit` | Set unit |
| GET | `/kdc101/device/list` | List D2XX devices |
| POST | `/kdc101/device/connect` | Connect KDC101 |
| POST | `/kdc101/device/disconnect` | Disconnect KDC101 |
| GET | `/kdc101/device/status` | KDC101 status |
| GET | `/kdc101/config/velocity` | Get velocity params |
| PUT | `/kdc101/config/velocity` | Set velocity params |
| GET | `/kdc101/config/stage` | Get stage config |
| PUT | `/kdc101/config/stage` | Set stage config |
| POST | `/kdc101/motion/home` | Home stage |
| POST | `/kdc101/motion/stop` | Stop stage |

### CSV Export Format

```csv
timestamp,position_mm,power,power_unit
1709472000.123,0.500,0.00123,W
1709472000.173,0.512,0.00125,W
...
```

When `start_mm` and `end_mm` query params provided, only rows within that position range are included.

## Frontend Design

### Technology

- Plain HTML/JS/CSS (no build step), consistent with existing UIs
- Chart.js 4 for scatter/line chart
- Dark theme matching PM100D and KDC101 pages
- Served by FastAPI as static file

### Layout

```
┌─────────────────────────────────────────────────────────────────┐
│  Coordinated Scan                                    [Status]   │
├──────────────────────┬──────────────────────────────────────────┤
│  SIDEBAR             │  MAIN AREA                               │
│                      │                                          │
│  Device Setup        │  Power vs Position Chart                 │
│  PM100D Config       │  (Chart.js scatter plot, live update)    │
│  Stage Config        │                                          │
│  Scan Setup          │  Range Selector (dual-handle slider)     │
│  Log                 │  Export (All CSV / Range CSV)             │
└──────────────────────┴──────────────────────────────────────────┘
```

### Sidebar Panels

1. **Device Setup**: Connect/disconnect both PM100D and KDC101 with status badges
2. **PM100D Config**: Wavelength, power range (auto/manual), averaging, unit
3. **Stage Config**: Velocity (mm/s), acceleration (mm/s²), home button, current position display
4. **Scan Setup**:
   - Mode toggle: Absolute | Relative
   - Absolute fields: Start position, End position
   - Relative fields: Distance, Direction (+/-)
   - Sampling interval (ms)
   - Estimated time display (updates live)
   - Start Scan / Stop Scan buttons
5. **Log**: Status messages

### Main Area

1. **Chart**: Power (Y) vs Position (X) scatter plot
   - Real-time updates during scan via SSE
   - Persists after scan completion
2. **Range Selector**: Dual-handle range slider below chart
   - Displays selected start/end positions
   - Shows point count within selection
3. **Export**: Two buttons — Export All CSV, Export Range CSV

### Key Behaviors

- Mode toggle shows/hides relevant input fields
- Time estimate updates as velocity/distance change
- Chart clears on new scan start
- Range slider defaults to full range after scan completes
- Export buttons disabled during scan, enabled after completion
- Both device connection statuses shown prominently
- Start Scan disabled unless both devices connected
