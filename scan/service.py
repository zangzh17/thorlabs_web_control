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
