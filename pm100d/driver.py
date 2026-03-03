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

    # --- Measurement ---

    def read_power(self) -> float:
        return float(self._query("MEAS:SCAL:POW?"))

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
