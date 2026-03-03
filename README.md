# Thorlabs Web Control

Browser-based control for Thorlabs instruments using WebUSB. Each device is a single static HTML file -- no backend server required. All communication happens directly between the browser and USB devices via WebUSB.

| Device | Description | Protocol |
|--------|-------------|----------|
| **PM100D** | Optical Power Meter | WebUSB + USBTMC/SCPI |
| **KDC101** | K-Cube DC Servo Motor Controller | WebUSB + FTDI + APT binary protocol |
| **Coordinated Scan** | PM100D + KDC101 spatial power scanning | Both via WebUSB |

## Architecture

```
Browser ──WebUSB──→ PM100D (USBTMC/SCPI)
Browser ──WebUSB──→ KDC101 (FTDI/APT)
```

No backend server needed. The HTML files can be served from any static file server (local or remote) -- the browser on the local machine handles all USB communication directly.

## Prerequisites

- **Browser**: Chrome or Edge (WebUSB support required)
- **WinUSB driver** for both devices, installed via [Zadig](https://zadig.akeo.ie/)
  - **PM100D**: replaces NI-VISA driver
  - **KDC101**: replaces FTDI D2XX driver (Thorlabs Kinesis)

## Quick Start

```bash
git clone https://github.com/zangzh17/thorlabs_web_control.git
cd thorlabs_web_control

# Serve with any static HTTP server
python -m http.server 8000
# or: npx serve
```

Open in Chrome/Edge:

- PM100D: `http://localhost:8000/pm100d/static/index.html`
- KDC101: `http://localhost:8000/kdc101/static/index.html`
- Coordinated Scan: `http://localhost:8000/scan/static/index.html`

Click "Connect USB" on each page to pair with the device.

> **Note**: Opening HTML files directly via `file://` may work, but some browsers restrict WebUSB on the file protocol. Using a local HTTP server is recommended.

## Modules

### PM100D -- Optical Power Meter

Real-time optical power display with configurable wavelength, averaging count, measurement unit, and range. Includes a live power chart.

### KDC101 -- K-Cube DC Servo Motor Controller

Position display with absolute move, relative move, jog, and home commands. Configurable velocity and acceleration. Includes a live position chart.

### Coordinated Scan

Coordinated spatial power scanning using both PM100D and KDC101. Supports relative and center-based scan modes. Live power-vs-position chart with crop lines for data selection. CSV export of scan results.

## Stage Configuration

The KDC101 reports position in encoder counts. Set the conversion factor for your stage:

| Stage | Counts per unit |
|-------|-----------------|
| Z812 (default) | 34,555 counts/mm |
| ZFS13 / ZFS25 | 34,304 counts/mm |
| MTS25 / MTS50 | 34,304 counts/mm |
| PRM1-Z8 (rotation) | 1,919.64 counts/deg |

## Zadig Setup

Both devices require the WinUSB driver installed via [Zadig](https://zadig.akeo.ie/):

1. Open Zadig
2. Go to **Options** and check **List All Devices**
3. Select the target device from the dropdown:
   - PM100D appears as "PM100D" or similar
   - KDC101 appears as "APT USB Device"
4. Set the target driver to **WinUSB**
5. Click **Replace Driver**

> **Warning**: Replacing the driver is not easily reversible. The original driver (NI-VISA for PM100D, FTDI D2XX for KDC101) must be manually reinstalled if you want to revert. Applications that depend on the original driver (e.g., Thorlabs Kinesis, NI MAX) will not work after the replacement (will only affect this computer).

## Project Structure

```
thorlabs/
├── pm100d/
│   └── static/
│       └── index.html          # PM100D Power Meter (WebUSB)
├── kdc101/
│   └── static/
│       └── index.html          # KDC101 Motor Controller (WebUSB)
├── scan/
│   └── static/
│       └── index.html          # Coordinated Scan (both devices via WebUSB)
├── .gitignore
└── README.md
```

## Dependencies

- [Chart.js](https://www.chartjs.org/) -- loaded from CDN, no install needed

## License

MIT
