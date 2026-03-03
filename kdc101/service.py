import logging
import threading
import time
from collections import deque

from kdc101.driver import KDC101Driver
from kdc101.schemas import PositionReading

logger = logging.getLogger(__name__)


class KDC101Service:
    """Thread-safe service layer with background position polling."""

    def __init__(self, buffer_size: int = 10000):
        self.driver = KDC101Driver()
        self._buffer: deque[PositionReading] = deque(maxlen=buffer_size)
        self._polling = False
        self._poll_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._driver_lock = threading.Lock()
        self._last_status: dict | None = None

    def connect(self, serial_number: str) -> None:
        with self._driver_lock:
            self.driver.connect(serial_number)

    def disconnect(self) -> None:
        self.stop_polling()
        with self._driver_lock:
            self.driver.disconnect()

    @property
    def is_connected(self) -> bool:
        return self.driver.is_connected

    # --- Device info (thread-safe) ----------------------------------------

    def get_hw_info(self) -> dict:
        with self._driver_lock:
            return self.driver.get_hw_info()

    def identify(self) -> None:
        with self._driver_lock:
            self.driver.identify()

    # --- Status (thread-safe) --------------------------------------------

    def get_status(self) -> dict:
        with self._driver_lock:
            return self.driver.get_status()

    @property
    def last_status(self) -> dict | None:
        with self._lock:
            return self._last_status

    # --- Configuration (thread-safe) -------------------------------------

    @property
    def counts_per_mm(self) -> float:
        return self.driver.counts_per_mm

    @counts_per_mm.setter
    def counts_per_mm(self, value: float) -> None:
        self.driver.counts_per_mm = value

    def get_velocity_params(self) -> dict:
        with self._driver_lock:
            return self.driver.get_velocity_params()

    def set_velocity_params(
        self, max_velocity_mm_s: float, acceleration_mm_s2: float
    ) -> None:
        with self._driver_lock:
            self.driver.set_velocity_params(max_velocity_mm_s, acceleration_mm_s2)

    # --- Motion (non-blocking, thread-safe) ------------------------------

    def home(self) -> None:
        """Start homing (non-blocking). Poll status to check completion."""
        with self._driver_lock:
            self.driver.home_start()

    def move_absolute(self, position_mm: float) -> None:
        """Start absolute move (non-blocking)."""
        with self._driver_lock:
            self.driver.move_absolute_start(position_mm)

    def move_relative(self, distance_mm: float) -> None:
        """Start relative move (non-blocking)."""
        with self._driver_lock:
            self.driver.move_relative_start(distance_mm)

    def jog(self, direction: int = 1) -> None:
        with self._driver_lock:
            self.driver.jog(direction)

    def stop(self, immediate: bool = False) -> None:
        with self._driver_lock:
            self.driver.stop(immediate)

    def enable(self) -> None:
        with self._driver_lock:
            self.driver.enable()

    def disable(self) -> None:
        with self._driver_lock:
            self.driver.disable()

    # --- Continuous position polling -------------------------------------

    def start_polling(self, interval_ms: int = 100) -> None:
        if self._polling:
            return
        self._stop_event.clear()
        self._polling = True
        self._poll_thread = threading.Thread(
            target=self._polling_loop,
            args=(interval_ms / 1000.0,),
            daemon=True,
        )
        self._poll_thread.start()

    def stop_polling(self) -> None:
        if not self._polling:
            return
        self._stop_event.set()
        if self._poll_thread is not None:
            self._poll_thread.join(timeout=5.0)
        self._polling = False
        self._poll_thread = None

    def _polling_loop(self, interval_s: float) -> None:
        logger.info("Position polling started (interval=%.3fs)", interval_s)
        while not self._stop_event.is_set():
            try:
                with self._driver_lock:
                    status = self.driver.get_status()
                reading = PositionReading(
                    timestamp=time.time(),
                    position_mm=status["position_mm"],
                    position_counts=status["position_counts"],
                    velocity=status["velocity"],
                    status_bits=status["status_bits"],
                )
                with self._lock:
                    self._buffer.append(reading)
                    self._last_status = status
            except Exception:
                logger.exception("Position poll failed")
            self._stop_event.wait(interval_s)
        logger.info("Position polling stopped")

    @property
    def is_polling(self) -> bool:
        return self._polling

    def get_latest_reading(self) -> PositionReading | None:
        with self._lock:
            return self._buffer[-1] if self._buffer else None

    def get_buffer(self, n: int = 100) -> list[PositionReading]:
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
