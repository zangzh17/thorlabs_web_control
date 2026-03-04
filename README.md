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

Coordinated spatial power scanning using both PM100D and KDC101.

- **Scan modes**: Relative (from current position) and center-based (symmetric around current position)
- **Sample extraction**: Set the number of uniformly spaced sample points (N) between draggable start/end markers; the N-2 interior points are marked on the chart, with endpoints indicated by the marker lines
- **Neighbor averaging**: Configurable averaging ratio (default 20%) -- for each sample point, power values within ±(ratio/2)% of the inter-sample spacing are averaged; the averaging windows are visualized as shaded regions on the chart
- **Display unit toggle**: Switch the chart between mW and dBm display with automatic data conversion and axis rescaling
- **CSV export**: Export raw scan data (position + power) or processed N-point data (averaged power only)

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

## Secondary Development Guide

When adapting this project's WebUSB code into another application, the following pitfalls are commonly encountered.

### USBTMC (PM100D): `transferOut` hangs after `claimInterface`

**Symptom:** `device.transferOut()` never resolves — the promise hangs forever with no error.

**Cause:** Bulk endpoints can be left in a stalled state from previous incomplete connections (browser tab closed mid-transfer, failed init, etc.). This project works on a fresh page load with no prior stale state, but integrating into a larger app often hits this.

**Fix:** After `claimInterface()`, call `clearHalt` on both endpoints:

```js
await device.claimInterface(ifaceNum);
try { await device.clearHalt('out', epOut); } catch {}
try { await device.clearHalt('in', epIn); } catch {}
```

Also wrap `transferOut` / `transferIn` with `Promise.race` timeouts so hangs become errors instead of silent freezes.

### USBTMC: Do NOT use an AsyncMutex around query()

**Symptom:** First `query()` call hangs at mutex `acquire()` even though nothing else has locked it.

**Cause:** Not fully diagnosed — possibly a subtle JS async scheduling issue. This project uses no mutex and works fine.

**Fix:** Remove the mutex. Ensure callers don't fire concurrent queries (e.g., use a sequential loop with `setTimeout` instead of `setInterval` for polling).

### FTDI/APT (KDC101): Synchronous read doesn't work

**Symptom:** `transferIn` returns incomplete data; parsing short buffers causes `"Offset is outside the bounds of the DataView"`.

**Cause:** FTDI chips fragment data across multiple USB packets, each prefixed with a 2-byte modem status header. A single `transferIn` call doesn't guarantee a complete APT message.

**Fix:** Use a background `_readLoop()` that continuously reads FTDI packets, strips the 2-byte headers, and appends payload to an `_rxBuffer`. Then parse complete APT messages from the buffer with `recvMessage()` / `waitForMessage()`.

Required FTDI init sequence (missing from naive implementations):

1. Reset device
2. Set baud rate (115200)
3. Set line properties (8N1)
4. Set flow control (none)
5. Purge RX buffer
6. Purge TX buffer
7. Set DTR high
8. Set RTS high
9. Send `HW_NO_FLASH_PROGRAMMING` (0x0018) before channel enable

### KDC101: `MOT_REQ_POSCOUNTER` may not get a response

**Symptom:** `getPosition()` using `MOT_REQ_POSCOUNTER` (0x0410) times out — no `MOT_GET_POSCOUNTER` (0x0411) response.

**Fix:** Use `MOT_REQ_DCSTATUSUPDATE` (0x0490) instead, which returns position as part of the status packet and is more reliably supported across firmware versions.

### Both devices need WinUSB driver via Zadig

On Windows, both PM100D and KDC101 need their default drivers replaced with WinUSB using [Zadig](https://zadig.akeo.ie/). Without this, `claimInterface()` will hang or fail. FTDI devices and USBTMC devices each need separate Zadig treatment. See [Zadig Setup](#zadig-setup) above for details.

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
