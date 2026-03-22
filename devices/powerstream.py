# =============================================================================
# devices/powerstream.py - EcoFlow PowerStream 600W / 800W
# Portiert von ha-ef-ble (Apache-2.0)
# =============================================================================

import logging
import sys
import os
from typing import Any, Optional

# wn511_sys_pb2 liegt im Hauptverzeichnis
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import wn511_sys_pb2

from protocol import Packet
from .base import EcoFlowDevice

log = logging.getLogger(__name__)


def _div10(value) -> float:
    return round(value / 10, 1)


class PowerStream(EcoFlowDevice):
    """
    EcoFlow PowerStream 600W / 800W

    MQTT Topics (Lesen):
      pv_power_1, pv_power_2          — PV Eingang je Panel (W)
      pv_voltage_1, pv_voltage_2      — PV Spannung (V)
      pv_current_1, pv_current_2      — PV Strom (A)
      battery_level                   — Batteriestand (%)
      battery_power                   — Batterie Leistung (W)
      inverter_power                  — Aktuelle Einspeisung (W)
      inverter_voltage                — Netzspannung (V)
      inverter_frequency              — Netzfrequenz (Hz)
      load_power                      — Einstellwert permanent_watts (W)
      llc_temperature, inverter_temperature, battery_temperature, pv_temperature_1/2

    MQTT Topics (Steuern):
      set/load_power    — Einspeiseleistung setzen (0-800 W)
      set/supply_priority — 0=Netz bevorzugen, 1=Batterie bevorzugen
      set/charge_limit_min — Minimaler Ladestand (0-30%)
      set/charge_limit_max — Maximaler Ladestand (50-100%)
    """

    DEVICE_TYPE   = "powerstream"
    SERIAL_PREFIX = ["HW51", "HW52"]

    # Packet-Parameter für PowerStream (aus ha-ef-ble powerstream.py)
    PACKET_VERSION = 0x13
    DST_INVERTER   = 0x35
    DST_DISPLAY    = 0x14

    def parse_data(self, packet: Packet) -> dict[str, Any]:
        """
        Parst eingehende Packets vom PowerStream.
        Matching auf (src, cmdSet, cmdId) wie in ha-ef-ble.
        """
        result = {}

        try:
            match (packet.src, packet.cmdSet, packet.cmdId):
                case (0x35, 0x14, 0x01):
                    # Haupt-Heartbeat: inverter_heartbeat
                    hb = wn511_sys_pb2.inverter_heartbeat()
                    hb.ParseFromString(packet.payload)
                    result = self._parse_heartbeat(hb)

                case (0x35, 0x14, 0x04):
                    hb2 = wn511_sys_pb2.inv_heartbeat_type2()
                    hb2.ParseFromString(packet.payload)
                    # lcd_show_soc ist der angezeigte Wert in der App
                    soc = hb2.new_psdr_heartbeat.f32_lcd_show_soc
                    if soc > 0:
                        result["battery_level"] = round(soc, 1)
                    # Zusätzliche nützliche Werte
                    if hb2.new_psdr_heartbeat.chg_remain_time > 0:
                        result["charge_time_min"] = hb2.new_psdr_heartbeat.chg_remain_time
                    if hb2.new_psdr_heartbeat.dsg_remain_time < 5999:
                        result["discharge_time_min"] = hb2.new_psdr_heartbeat.dsg_remain_time

                case (0x35, 0x14, 0x88):
                    # Power Pack — nur ACK senden, keine Datenpunkte
                    log.debug("[%s] Power pack received, ACK needed", self.name)

                case _:
                    log.debug("[%s] Unbekanntes Packet: src=0x%02X cmdSet=0x%02X cmdId=0x%02X",
                              self.name, packet.src, packet.cmdSet, packet.cmdId)

        except Exception as e:
            log.warning("[%s] Protobuf Parse-Fehler: %s", self.name, e)

        return result

    def _parse_heartbeat(self, hb) -> dict[str, Any]:
        """Parst inverter_heartbeat Protobuf Message."""
        result = {}

        def _set(key, value, transform=None):
            if value != 0 or key in ("load_power",):
                result[key] = transform(value) if transform else value

        _set("pv_power_1",          hb.pv1_input_watts,  _div10)
        _set("pv_voltage_1",        hb.pv1_input_volt,   _div10)
        _set("pv_current_1",        hb.pv1_input_cur,    _div10)
        _set("pv_temperature_1",    hb.pv1_temp,         _div10)

        _set("pv_power_2",          hb.pv2_input_watts,  _div10)
        _set("pv_voltage_2",        hb.pv2_input_volt,   _div10)
        _set("pv_current_2",        hb.pv2_input_cur,    _div10)
        _set("pv_temperature_2",    hb.pv2_temp,         _div10)

        _set("battery_power",       hb.bat_input_watts,  _div10)
        _set("battery_temperature", hb.bat_temp,         _div10)

        _set("inverter_power",      hb.inv_output_watts, _div10)
        _set("inverter_voltage",    hb.inv_op_volt,      _div10)
        _set("inverter_frequency",  hb.inv_freq,         _div10)
        _set("inverter_temperature",hb.inv_temp,         _div10)
        _set("inverter_current",    hb.inv_output_cur,
             lambda x: round(x / 1000, 2))

        _set("llc_temperature",     hb.llc_temp,         _div10)
        _set("charge_limit_max",    hb.upper_limit)
        _set("charge_limit_min",    hb.lower_limit)
        _set("supply_priority",     hb.supply_priority)
        _set("load_power",          hb.permanent_watts,  _div10)

        return result

    def build_set_command(self, key: str, value: Any) -> Optional[Packet]:
        """
        Baut ein Steuer-Packet für den PowerStream.

        Unterstützte Keys:
          load_power (0-800 W)      → Einspeiseleistung
          supply_priority (0 oder 1)→ 0=Netz, 1=Batterie
          charge_limit_min (0-30)   → Minimaler SOC
          charge_limit_max (50-100) → Maximaler SOC
        """
        try:
            if key == "load_power":
                watts = max(0, min(800, float(value)))
                msg   = wn511_sys_pb2.permanent_watts_pack(
                    permanent_watts=int(watts * 10)
                )
                return self._make_packet(msg.SerializeToString(), cmd_id=0x81)

            elif key == "supply_priority":
                prio = int(value)
                msg  = wn511_sys_pb2.supply_priority_pack(supply_priority=prio)
                return self._make_packet(msg.SerializeToString(), cmd_id=0x82)

            elif key == "charge_limit_min":
                limit = max(0, min(30, int(value)))
                msg   = wn511_sys_pb2.bat_lower_pack(lower_limit=limit)
                return self._make_packet(msg.SerializeToString(), cmd_id=0x84)

            elif key == "charge_limit_max":
                limit = max(50, min(100, int(value)))
                msg   = wn511_sys_pb2.bat_upper_pack(upper_limit=limit)
                return self._make_packet(msg.SerializeToString(), cmd_id=0x85)

            else:
                log.warning("[%s] Unbekannter Set-Key: %s", self.name, key)
                return None

        except Exception as e:
            log.error("[%s] Fehler beim Bauen des Set-Befehls: %s", self.name, e)
            return None

    def _make_packet(self, payload: bytes, cmd_id: int,
                     dst: int = None) -> Packet:
        """Erstellt ein Packet für den PowerStream."""
        return Packet(
            src=0x21,
            dst=dst if dst else self.DST_INVERTER,
            cmd_set=0x14,
            cmd_id=cmd_id,
            payload=payload,
            dsrc=0x01,
            ddst=0x01,
            version=self.PACKET_VERSION,
        )
