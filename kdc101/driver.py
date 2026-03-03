import struct
import time

import ftd2xx

# ---------------------------------------------------------------------------
# APT protocol constants
# ---------------------------------------------------------------------------
SOURCE = 0x01  # Host (PC)
DEST = 0x50  # Generic USB unit

# Message IDs
HW_REQ_INFO = 0x0005
HW_GET_INFO = 0x0006
HW_NO_FLASH_PROGRAMMING = 0x0018

MOD_IDENTIFY = 0x0223
MOD_SET_CHANENABLESTATE = 0x0210
MOD_REQ_CHANENABLESTATE = 0x0211
MOD_GET_CHANENABLESTATE = 0x0212

MOT_SET_VELPARAMS = 0x0413
MOT_REQ_VELPARAMS = 0x0414
MOT_GET_VELPARAMS = 0x0415

MOT_SET_JOGPARAMS = 0x0416
MOT_REQ_JOGPARAMS = 0x0417
MOT_GET_JOGPARAMS = 0x0418

MOT_SET_MOVERELPARAMS = 0x0445
MOT_REQ_MOVERELPARAMS = 0x0446
MOT_GET_MOVERELPARAMS = 0x0447
MOT_MOVE_RELATIVE = 0x0448

MOT_SET_MOVEABSPARAMS = 0x0450
MOT_REQ_MOVEABSPARAMS = 0x0451
MOT_GET_MOVEABSPARAMS = 0x0452
MOT_MOVE_ABSOLUTE = 0x0453

MOT_MOVE_HOME = 0x0443
MOT_MOVE_HOMED = 0x0444
MOT_MOVE_COMPLETED = 0x0464
MOT_MOVE_STOP = 0x0465
MOT_MOVE_STOPPED = 0x0466
MOT_MOVE_JOG = 0x046A

MOT_REQ_POSCOUNTER = 0x0411
MOT_GET_POSCOUNTER = 0x0412

MOT_REQ_DCSTATUSUPDATE = 0x0490
MOT_GET_DCSTATUSUPDATE = 0x0491

# Status bits
STATUS_FWD_HW_LIM = 0x00000001
STATUS_REV_HW_LIM = 0x00000002
STATUS_MOVING_FWD = 0x00000010
STATUS_MOVING_REV = 0x00000020
STATUS_JOGGING_FWD = 0x00000040
STATUS_JOGGING_REV = 0x00000080
STATUS_HOMING = 0x00000200
STATUS_HOMED = 0x00000400
STATUS_TRACKING = 0x00001000
STATUS_SETTLED = 0x00002000
STATUS_MOTION_ERROR = 0x00004000
STATUS_CURRENT_LIMIT = 0x01000000
STATUS_ENABLED = 0x80000000

MOVING_BITS = (
    STATUS_MOVING_FWD
    | STATUS_MOVING_REV
    | STATUS_JOGGING_FWD
    | STATUS_JOGGING_REV
    | STATUS_HOMING
)

# APT time base for KDC101 velocity / acceleration encoding
T_APT = 2048 / 6_000_000  # ≈ 3.41333e-4 s

# Default encoder counts for common stages
DEFAULT_COUNTS_PER_MM = 34555  # Z812 stage


class KDC101Driver:
    """Low-level APT binary protocol driver for Thorlabs KDC101 via FTDI D2XX."""

    def __init__(self, counts_per_mm: float = DEFAULT_COUNTS_PER_MM):
        self._dev: ftd2xx.FTD2XX | None = None
        self._counts_per_mm = counts_per_mm

    # --- Device discovery ------------------------------------------------

    @staticmethod
    def list_devices() -> list[dict]:
        """List available FTDI D2XX devices (Thorlabs APT controllers)."""
        result = []
        try:
            num = ftd2xx.createDeviceInfoList()
            for i in range(num):
                info = ftd2xx.getDeviceInfoDetail(i)
                sn = info["serial"]
                desc = info["description"]
                result.append(
                    {
                        "index": i,
                        "serial_number": sn.decode() if isinstance(sn, bytes) else str(sn),
                        "description": desc.decode() if isinstance(desc, bytes) else str(desc),
                    }
                )
        except Exception:
            pass
        return result

    # --- Connection ------------------------------------------------------

    def connect(self, serial_number: str) -> None:
        """Connect to KDC101 by serial number via FTDI D2XX."""
        if self._dev is not None:
            self.disconnect()
        sn = serial_number.encode() if isinstance(serial_number, str) else serial_number
        self._dev = ftd2xx.openEx(sn)
        self._dev.setBaudRate(115200)
        self._dev.setDataCharacteristics(8, 0, 0)  # 8N1
        self._dev.setFlowControl(0, 0, 0)  # no flow control
        self._dev.setTimeouts(500, 500)  # read/write timeout ms
        self._dev.purge(1 | 2)  # flush rx + tx
        time.sleep(0.05)
        # Disable flash programming (recommended after connect)
        self._send_short(HW_NO_FLASH_PROGRAMMING, 0, 0)
        time.sleep(0.1)
        # Enable channel 1
        self._send_short(MOD_SET_CHANENABLESTATE, 0x01, 0x01)
        time.sleep(0.1)

    def disconnect(self) -> None:
        if self._dev is not None:
            try:
                self._dev.close()
            except Exception:
                pass
            self._dev = None

    @property
    def is_connected(self) -> bool:
        return self._dev is not None

    # --- Encoder conversion config ---------------------------------------

    @property
    def counts_per_mm(self) -> float:
        return self._counts_per_mm

    @counts_per_mm.setter
    def counts_per_mm(self, value: float) -> None:
        if value <= 0:
            raise ValueError("counts_per_mm must be positive")
        self._counts_per_mm = value

    # --- Low-level protocol ---------------------------------------------

    def _write(self, data: bytes) -> None:
        if self._dev is None:
            raise ConnectionError("KDC101 not connected")
        self._dev.write(data)

    def _read(self, n: int, timeout_ms: int = 500) -> bytes | None:
        """Read exactly n bytes. Returns None if not enough data within timeout."""
        if self._dev is None:
            raise ConnectionError("KDC101 not connected")
        self._dev.setTimeouts(timeout_ms, 500)
        buf = b""
        deadline = time.monotonic() + timeout_ms / 1000.0
        while len(buf) < n:
            remaining = n - len(buf)
            chunk = self._dev.read(remaining)
            if chunk:
                buf += chunk
            if len(buf) >= n:
                break
            if time.monotonic() >= deadline:
                break
            time.sleep(0.001)
        return buf if len(buf) == n else None

    def _send_short(self, msg_id: int, param1: int = 0, param2: int = 0) -> None:
        """Send a 6-byte header-only APT message."""
        packet = struct.pack("<HBBBB", msg_id, param1, param2, DEST, SOURCE)
        self._write(packet)

    def _send_long(self, msg_id: int, data: bytes) -> None:
        """Send a header + data APT message."""
        header = struct.pack("<HHBB", msg_id, len(data), DEST | 0x80, SOURCE)
        self._write(header + data)

    def _recv_message(self, timeout: float = 1.0) -> tuple | None:
        """Read one APT message.

        Returns:
            For header-only:  (msg_id, param1, param2)
            For data message:  (msg_id, data_bytes)
            None on timeout.
        """
        timeout_ms = max(1, int(timeout * 1000))
        header = self._read(6, timeout_ms)
        if header is None:
            return None
        msg_id = struct.unpack_from("<H", header, 0)[0]
        if header[4] & 0x80:  # data message
            data_len = struct.unpack_from("<H", header, 2)[0]
            data = self._read(data_len, timeout_ms)
            if data is None:
                return None
            return (msg_id, data)
        else:  # header-only
            return (msg_id, header[2], header[3])

    def _transact(
        self,
        req_id: int,
        resp_id: int,
        param1: int = 0,
        param2: int = 0,
        data: bytes | None = None,
        timeout: float = 5.0,
    ) -> tuple:
        """Send a request and wait for a specific response message."""
        if data is not None:
            self._send_long(req_id, data)
        else:
            self._send_short(req_id, param1, param2)

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            remaining = max(0.1, deadline - time.monotonic())
            msg = self._recv_message(timeout=remaining)
            if msg is not None and msg[0] == resp_id:
                return msg
        raise TimeoutError(f"No response 0x{resp_id:04X} within {timeout}s")

    # --- Unit conversion helpers ----------------------------------------

    def _mm_to_counts(self, mm: float) -> int:
        return int(round(mm * self._counts_per_mm))

    def _counts_to_mm(self, counts: int) -> float:
        return counts / self._counts_per_mm

    def _vel_to_apt(self, vel_mm_s: float) -> int:
        return int(round(vel_mm_s * self._counts_per_mm * T_APT * 65536))

    def _apt_to_vel(self, apt_vel: int) -> float:
        divisor = self._counts_per_mm * T_APT * 65536
        return apt_vel / divisor if divisor else 0.0

    def _acc_to_apt(self, acc_mm_s2: float) -> int:
        return int(round(acc_mm_s2 * self._counts_per_mm * T_APT * T_APT * 65536))

    def _apt_to_acc(self, apt_acc: int) -> float:
        divisor = self._counts_per_mm * T_APT * T_APT * 65536
        return apt_acc / divisor if divisor else 0.0

    # --- Device info -----------------------------------------------------

    def identify(self) -> None:
        """Flash the front panel LED."""
        self._send_short(MOD_IDENTIFY, 0, 0)

    def get_hw_info(self) -> dict:
        """Query hardware information."""
        msg = self._transact(HW_REQ_INFO, HW_GET_INFO, 0, 0)
        data = msg[1]
        serial_num = struct.unpack_from("<I", data, 0)[0]
        model = data[4:12].decode("ascii", errors="replace").strip("\x00 ")
        fw_minor, fw_interim, fw_major, _ = struct.unpack_from("<BBBB", data, 14)
        hw_version = struct.unpack_from("<H", data, 78)[0]
        num_channels = struct.unpack_from("<H", data, 82)[0]
        return {
            "serial_number": serial_num,
            "model": model,
            "firmware_version": f"{fw_major}.{fw_interim}.{fw_minor}",
            "hw_version": hw_version,
            "num_channels": num_channels,
        }

    # --- Status ----------------------------------------------------------

    def get_status(self) -> dict:
        """Request and parse DC status update (position, velocity, status bits)."""
        msg = self._transact(MOT_REQ_DCSTATUSUPDATE, MOT_GET_DCSTATUSUPDATE, 0x01, 0)
        data = msg[1]
        (position,) = struct.unpack_from("<i", data, 2)  # signed int32
        (velocity,) = struct.unpack_from("<H", data, 6)
        (status_bits,) = struct.unpack_from("<I", data, 10)
        return {
            "position_counts": position,
            "position_mm": self._counts_to_mm(position),
            "velocity": velocity,
            "status_bits": status_bits,
            "is_moving": bool(status_bits & MOVING_BITS),
            "is_homed": bool(status_bits & STATUS_HOMED),
            "is_homing": bool(status_bits & STATUS_HOMING),
            "fwd_limit": bool(status_bits & STATUS_FWD_HW_LIM),
            "rev_limit": bool(status_bits & STATUS_REV_HW_LIM),
            "is_enabled": bool(status_bits & STATUS_ENABLED),
            "is_settled": bool(status_bits & STATUS_SETTLED),
            "motion_error": bool(status_bits & STATUS_MOTION_ERROR),
        }

    def get_position_mm(self) -> float:
        return self.get_status()["position_mm"]

    # --- Channel enable / disable ----------------------------------------

    def enable(self) -> None:
        self._send_short(MOD_SET_CHANENABLESTATE, 0x01, 0x01)

    def disable(self) -> None:
        self._send_short(MOD_SET_CHANENABLESTATE, 0x01, 0x02)

    # --- Velocity parameters ---------------------------------------------

    def get_velocity_params(self) -> dict:
        msg = self._transact(MOT_REQ_VELPARAMS, MOT_GET_VELPARAMS, 0x01, 0)
        data = msg[1]
        (min_vel,) = struct.unpack_from("<I", data, 2)
        (accel,) = struct.unpack_from("<I", data, 6)
        (max_vel,) = struct.unpack_from("<I", data, 10)
        return {
            "min_velocity_mm_s": self._apt_to_vel(min_vel),
            "acceleration_mm_s2": self._apt_to_acc(accel),
            "max_velocity_mm_s": self._apt_to_vel(max_vel),
        }

    def set_velocity_params(
        self,
        max_velocity_mm_s: float,
        acceleration_mm_s2: float,
        min_velocity_mm_s: float = 0.0,
    ) -> None:
        data = struct.pack(
            "<HIII",
            0x01,  # channel
            self._vel_to_apt(min_velocity_mm_s),
            self._acc_to_apt(acceleration_mm_s2),
            self._vel_to_apt(max_velocity_mm_s),
        )
        self._send_long(MOT_SET_VELPARAMS, data)

    # --- Homing ----------------------------------------------------------

    def home(self, timeout: float = 60.0) -> None:
        """Start homing and block until complete."""
        self._send_short(MOT_MOVE_HOME, 0x01, 0)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            remaining = max(0.1, deadline - time.monotonic())
            msg = self._recv_message(timeout=remaining)
            if msg is not None and msg[0] == MOT_MOVE_HOMED:
                return
        raise TimeoutError(f"Home not completed within {timeout}s")

    def home_start(self) -> None:
        """Start homing without blocking."""
        self._send_short(MOT_MOVE_HOME, 0x01, 0)

    # --- Motion ----------------------------------------------------------

    def move_absolute(self, position_mm: float, timeout: float = 60.0) -> None:
        """Move to absolute position (blocking)."""
        counts = self._mm_to_counts(position_mm)
        data = struct.pack("<Hi", 0x01, counts)
        self._send_long(MOT_MOVE_ABSOLUTE, data)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            remaining = max(0.1, deadline - time.monotonic())
            msg = self._recv_message(timeout=remaining)
            if msg is not None and msg[0] == MOT_MOVE_COMPLETED:
                return
        raise TimeoutError(f"Move absolute not completed within {timeout}s")

    def move_absolute_start(self, position_mm: float) -> None:
        """Start absolute move without blocking."""
        counts = self._mm_to_counts(position_mm)
        data = struct.pack("<Hi", 0x01, counts)
        self._send_long(MOT_MOVE_ABSOLUTE, data)

    def move_relative(self, distance_mm: float, timeout: float = 60.0) -> None:
        """Move by relative distance (blocking)."""
        counts = self._mm_to_counts(distance_mm)
        data = struct.pack("<Hi", 0x01, counts)
        self._send_long(MOT_MOVE_RELATIVE, data)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            remaining = max(0.1, deadline - time.monotonic())
            msg = self._recv_message(timeout=remaining)
            if msg is not None and msg[0] == MOT_MOVE_COMPLETED:
                return
        raise TimeoutError(f"Move relative not completed within {timeout}s")

    def move_relative_start(self, distance_mm: float) -> None:
        """Start relative move without blocking."""
        counts = self._mm_to_counts(distance_mm)
        data = struct.pack("<Hi", 0x01, counts)
        self._send_long(MOT_MOVE_RELATIVE, data)

    def jog(self, direction: int = 1) -> None:
        """Jog in specified direction. 1=forward, 2=reverse."""
        if direction not in (1, 2):
            raise ValueError("direction must be 1 (forward) or 2 (reverse)")
        self._send_short(MOT_MOVE_JOG, 0x01, direction)

    def stop(self, immediate: bool = False) -> None:
        """Stop motion. immediate=True for abrupt stop, False for profiled stop."""
        stop_mode = 0x01 if immediate else 0x02
        self._send_short(MOT_MOVE_STOP, 0x01, stop_mode)
        # Try to read the MOVE_STOPPED response (non-critical)
        try:
            self._recv_message(timeout=1.0)
        except Exception:
            pass
