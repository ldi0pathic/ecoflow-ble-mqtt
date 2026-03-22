# =============================================================================
# devices/__init__.py - Geräte-Registry
# Neues Gerät hinzufügen: import + in DEVICE_REGISTRY eintragen
# =============================================================================

from typing import Optional
from .base import EcoFlowDevice
from .powerstream import PowerStream

# --- Alle unterstützten Gerätetypen -----------------------------------------
# Key = type-String aus config.py
DEVICE_REGISTRY: dict[str, type[EcoFlowDevice]] = {
    "powerstream": PowerStream,

    # Später einfach hinzufügen:
    # "delta2":    Delta2,
    # "delta2max": Delta2Max,
}

# --- Serienpräfix → Klasse Mapping (für automatisches Erkennen beim Scan) ----
SERIAL_PREFIX_MAP: dict[str, type[EcoFlowDevice]] = {}
for _cls in DEVICE_REGISTRY.values():
    for _prefix in _cls.SERIAL_PREFIX:
        SERIAL_PREFIX_MAP[_prefix.upper()] = _cls


def create_device(config: dict) -> EcoFlowDevice:
    """
    Erstellt eine Geräteinstanz aus einem Config-Dict.
    Wirft ValueError wenn der type unbekannt ist.
    """
    device_type = config.get("type", "").lower()
    cls = DEVICE_REGISTRY.get(device_type)
    if not cls:
        raise ValueError(
            f"Unbekannter Gerätetyp: '{device_type}'. "
            f"Unterstützt: {list(DEVICE_REGISTRY.keys())}"
        )
    return cls(
        name    = config["name"],
        address = config.get("address", ""),
        user_id = config["user_id"],
    )


def detect_device_type(serial_or_name: str) -> Optional[type[EcoFlowDevice]]:
    """Erkennt den Gerätetyp anhand der Seriennummer (für BLE-Scan)."""
    upper = serial_or_name.upper()
    for prefix, cls in SERIAL_PREFIX_MAP.items():
        if upper.startswith(prefix):
            return cls
    return None

