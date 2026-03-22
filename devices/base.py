# =============================================================================
# devices/base.py - Basis-Klasse für alle EcoFlow Geräte
# Neue Geräte (Delta 2, Delta 2 Max, etc.) erben von dieser Klasse
# =============================================================================

import logging
import asyncio
from abc import ABC, abstractmethod
from typing import Optional, Callable, Any

log = logging.getLogger(__name__)


class EcoFlowDevice(ABC):
    """
    Abstrakte Basisklasse für alle EcoFlow BLE Geräte.

    So fügst du ein neues Gerät hinzu:
    1. Neue Datei in devices/ anlegen (z.B. delta2.py)
    2. Von EcoFlowDevice erben
    3. DEVICE_TYPE, SERIAL_PREFIX und _parse_data() implementieren
    4. In devices/__init__.py registrieren
    """

    # --- Diese Konstanten MÜSSEN in jeder Unterklasse gesetzt werden ---------
    DEVICE_TYPE   : str       = ""        # z.B. "powerstream"
    SERIAL_PREFIX : list[str] = []        # z.B. ["HW51"]  ← Seriennummer-Präfix

    def __init__(self, name: str, address: str, user_id: int):
        self.name     = name        # MQTT-Topic-Präfix
        self.address  = address     # BLE MAC-Adresse (leer = noch nicht bekannt)
        self.user_id  = user_id
        self._state   : dict[str, Any] = {}
        self._on_state_change: Optional[Callable] = None

    # --- Callback setzen -----------------------------------------------------

    def set_state_callback(self, callback: Callable[[str, dict], None]):
        """
        Callback wird aufgerufen wenn neue Daten vom Gerät ankommen.
        Parameter: (device_name, state_dict)
        """
        self._on_state_change = callback

    # --- Abstrakte Methoden --------------------------------------------------

    @abstractmethod
    def parse_data(self, decrypted_payload: bytes) -> dict[str, Any]:
        """
        Parst den entschlüsselten Payload und gibt ein Dict mit Datenpunkten zurück.
        Beispiel: {"pv1_watts": 245.3, "battery_soc": 78, ...}
        Muss in jeder Geräteklasse implementiert werden.
        """
        pass

    @abstractmethod
    def build_set_command(self, key: str, value: Any) -> Optional[bytes]:
        """
        Baut einen Steuerbefehl-Payload.
        Beispiel: build_set_command("permanent_watts", 600)
        Gibt None zurück wenn der Key unbekannt ist.
        """
        pass

    # --- Hilfsmethoden -------------------------------------------------------

    def update_state(self, new_values: dict[str, Any]):
        """Aktualisiert den internen State und ruft Callback auf."""
        changed = {}
        for key, value in new_values.items():
            if self._state.get(key) != value:
                self._state[key] = value
                changed[key] = value

        if changed and self._on_state_change:
            self._on_state_change(self.name, changed)

    def get_state(self) -> dict[str, Any]:
        return dict(self._state)

    @classmethod
    def matches_serial(cls, serial: str) -> bool:
        """Prüft ob eine Seriennummer zu diesem Gerätetyp passt."""
        return any(serial.upper().startswith(p.upper()) for p in cls.SERIAL_PREFIX)
