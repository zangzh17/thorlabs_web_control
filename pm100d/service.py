import logging
import threading
import time
from collections import deque

from pm100d.driver import PM100DDriver
from pm100d.schemas import PowerReading

logger = logging.getLogger(__name__)


class PM100DService:
    """Thread-safe service layer with background acquisition."""

    def __init__(self, buffer_size: int = 10000):
        self.driver = PM100DDriver()
        self._buffer: deque[PowerReading] = deque(maxlen=buffer_size)
        self._acquiring = False
        self._acq_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._driver_lock = threading.Lock()
        self._cached_unit: str = "W"

    def connect(self, visa_resource: str, timeout_ms: int = 5000) -> None:
        with self._driver_lock:
            self.driver.connect(visa_resource, timeout_ms)

    def disconnect(self) -> None:
        self.stop_continuous_acquisition()
        with self._driver_lock:
            self.driver.disconnect()

    @property
    def is_connected(self) -> bool:
        return self.driver.is_connected

    def read_power(self) -> PowerReading:
        with self._driver_lock:
            power = self.driver.read_power()
            unit = self.driver.power_unit
        self._cached_unit = unit
        return PowerReading(timestamp=time.time(), power=power, unit=unit)

    def _read_power_fast(self) -> PowerReading:
        """Read power only (skip unit query) for high-speed acquisition."""
        with self._driver_lock:
            power = self.driver.read_power()
        return PowerReading(timestamp=time.time(), power=power, unit=self._cached_unit)

    # --- Continuous Acquisition ---

    def start_continuous_acquisition(self, interval_ms: int = 100) -> None:
        if self._acquiring:
            return
        # Cache unit before starting fast loop
        try:
            with self._driver_lock:
                self._cached_unit = self.driver.power_unit
        except Exception:
            pass
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
        logger.info("Acquisition loop started (interval=%.3fs)", interval_s)
        while not self._stop_event.is_set():
            try:
                reading = self._read_power_fast()
                with self._lock:
                    self._buffer.append(reading)
            except Exception:
                logger.exception("Acquisition read failed")
            self._stop_event.wait(interval_s)
        logger.info("Acquisition loop stopped")

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
