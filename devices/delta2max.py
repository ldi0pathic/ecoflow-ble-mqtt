# =============================================================================
# devices/delta2max.py - EcoFlow Delta 2 Max
# Basierend auf den Paketstrukturen aus ha-ef-ble (_delta2_base.py + delta2_max.py).
#
# Paket-Routing (src, cmdSet, cmdId):
#   (0x02, 0x20, 0x02)  → PD Heartbeat      (Mr350PdHeartbeatDelta2Max)
#   (0x03, 0x03, 0x0E)  → Kit-Details       (Extra-Batterien, noch unvollständig)
#   (0x03, 0x20, 0x02)  → EMS Heartbeat     (DirectEmsDeltaHeartbeatPack)
#   (0x03, 0x20, 0x32)  → BMS Main          (DirectBmsMDeltaHeartbeatPack)
#   (0x06, 0x20, 0x32)  → BMS Extra Bat 1   (DirectBmsMDeltaHeartbeatPack)
#   (0x04, *, 0x02)     → Inverter          (DirectInvDeltaHeartbeatPack)
#   (0x05, 0x20, 0x02)  → MPPT              (Mr350MpptHeart)
#
# Initial-Requests (einmalig nach Auth gesendet, Gerät antwortet + sendet HBs):
#   dst=0x02 cmdSet=0x20 cmdId=0x02 → PD anfordern
#   dst=0x03 cmdSet=0x20 cmdId=0x02 → EMS anfordern
#   dst=0x03 cmdSet=0x20 cmdId=0x32 → BMS anfordern
#   dst=0x04 cmdSet=0x20 cmdId=0x02 → INV anfordern
#   dst=0x05 cmdSet=0x20 cmdId=0x02 → MPPT anfordern
# =============================================================================

from __future__ import annotations

import logging
from typing import Annotated, Any, Optional

from protocol import Packet
from .base import EcoFlowDevice
from .rawdata import RawData

log = logging.getLogger(__name__)


# =============================================================================
# Binärstrukturen (aus ha-ef-ble model/__init__.py portiert)
# =============================================================================

class BasePdHeart(RawData):
    model: Annotated[int, "B"]
    error_code: Annotated[bytes, "4s"]
    sys_ver: Annotated[bytes, "4s"]
    wifi_ver: Annotated[bytes, "4s"]
    wifi_auto_recovery: Annotated[int, "B"]
    soc: Annotated[int, "B"]
    watts_out_sum: Annotated[int, "H"]
    watts_in_sum: Annotated[int, "H"]
    remain_time: Annotated[int, "i"]
    quiet_mode: Annotated[int, "B"]
    dc_out_state: Annotated[int, "B"]
    usb1_watt: Annotated[int, "B"]
    usb2_watt: Annotated[int, "B"]
    qc_usb1_watt: Annotated[int, "B"]
    qc_usb2_watt: Annotated[int, "B"]
    typec1_watts: Annotated[int, "B"]
    typec2_watts: Annotated[int, "B"]
    typec1_temp: Annotated[int, "B"]
    typec2_temp: Annotated[int, "B"]
    car_state: Annotated[int, "B"]
    car_watts: Annotated[int, "B"]
    car_temp: Annotated[int, "B"]
    standby_min: Annotated[int, "H"]
    lcd_off_sec: Annotated[int, "H"]
    lcd_brightness: Annotated[int, "B"]
    dc_chg_power: Annotated[int, "I"]
    sun_chg_power: Annotated[int, "I"]
    ac_chg_power: Annotated[int, "I"]
    dc_dsg_power: Annotated[int, "I"]
    ac_dsg_power: Annotated[int, "I"]
    usb_used_time: Annotated[int, "I"]
    usb_qc_used_time: Annotated[int, "I"]
    type_c_used_time: Annotated[int, "I"]
    car_used_time: Annotated[int, "I"]
    inv_used_time: Annotated[int, "I"]
    dc_in_used_time: Annotated[int, "I"]
    mppt_used_time: Annotated[int, "I"]


class Mr350PdHeartbeatCore(BasePdHeart):
    bms_kit_state: Annotated[int, "H"]
    other_kit_state: Annotated[int, "B"]
    reversed: Annotated[int, "H"]
    sys_chg_flag: Annotated[int, "B"]
    wifi_rssi: Annotated[int, "B"]
    wireless_watts: Annotated[int, "B"]
    screen_state: Annotated[bytes, "14s"]


class Mr350PdHeartbeatDelta2Max(Mr350PdHeartbeatCore):
    """PD Heartbeat spezifisch für Delta 2 Max (src=0x02)"""
    first_xt150_watts: Annotated[int, "H"]
    second_xt150_watts: Annotated[int, "H"]
    inv_in_watts: Annotated[int, "H"]
    inv_out_watts: Annotated[int, "H"]
    pv1_charge_type: Annotated[int, "B"]
    pv1_charge_watts: Annotated[int, "H"]
    pv2_charge_type: Annotated[int, "B"]
    pv2_charge_watts: Annotated[int, "H"]
    pv_charge_prio_set: Annotated[int, "B"]
    ac_auto_on_cfg_set: Annotated[int, "B"]
    ac_auto_out_config: Annotated[int, "B"]
    main_ac_out_soc: Annotated[int, "B"]
    ac_auto_out_pause: Annotated[int, "B"]
    watthisconfig: Annotated[int, "B"]
    bp_power_soc: Annotated[int, "B"]
    hysteresis_add: Annotated[int, "B"]
    relayswitchcnt: Annotated[int, "I"]


class BaseMpptHeart(RawData):
    fault_code: Annotated[int, "I"]
    sw_ver: Annotated[bytes, "4s"]
    in_vol: Annotated[int, "I"]
    in_amp: Annotated[int, "I"]
    in_watts: Annotated[int, "H"]
    out_val: Annotated[int, "I"]
    out_amp: Annotated[int, "I"]
    out_watts: Annotated[int, "H"]
    mppt_temp: Annotated[int, "h"]
    xt60_chg_type: Annotated[int, "B"]
    cfg_chg_type: Annotated[int, "B"]
    chg_type: Annotated[int, "B"]
    chg_state: Annotated[int, "B"]
    dcdc_12v_vol: Annotated[int, "I"]
    dcdc_12v_amp: Annotated[int, "I"]
    dcdc_12v_watts: Annotated[int, "H"]
    car_out_vol: Annotated[int, "I"]
    car_out_amp: Annotated[int, "I"]
    car_out_watts: Annotated[int, "H"]
    car_temp: Annotated[int, "h"]
    car_state: Annotated[int, "B"]
    dc24v_temp: Annotated[int, "h"]
    dc24v_state: Annotated[int, "B"]
    chg_pause_flag: Annotated[int, "B"]
    cfg_dc_chg_current: Annotated[int, "I"]


class Mr350MpptHeart(BaseMpptHeart):
    """MPPT Heartbeat für Delta 2 Max (src=0x05, zwei PV-Eingänge)"""
    pv2_in_vol: Annotated[int, "I"]
    pv2_in_amp: Annotated[int, "I"]
    pv2_in_watts: Annotated[int, "H"]
    pv2_mppt_temp: Annotated[int, "H"]
    pv2_xt60_chg_type: Annotated[int, "B"]
    pv2_cfg_chg_type: Annotated[int, "B"]
    pv2_chg_type: Annotated[int, "B"]
    pv2_chg_state: Annotated[int, "B"]
    pv2_chg_pause_flag: Annotated[int, "B"]
    car_standby_mins: Annotated[int, "H"]
    res: Annotated[bytes, "8s"]
    padding: Annotated[bytes, "1s"]


class DirectInvDeltaHeartbeatPack(RawData):
    """Inverter Heartbeat (src=0x04)"""
    err_code: Annotated[int, "I"]
    sys_ver: Annotated[int, "I"]
    charger_type: Annotated[int, "B"]
    input_watts: Annotated[int, "H"]
    output_watts: Annotated[int, "H"]
    inv_type: Annotated[int, "B"]
    inv_out_vol: Annotated[int, "I"]
    inv_out_amp: Annotated[int, "I"]
    inv_out_freq: Annotated[int, "B"]
    ac_in_vol: Annotated[int, "I"]
    ac_in_amp: Annotated[int, "I"]
    ac_in_freq: Annotated[int, "B"]
    out_temp: Annotated[int, "H"]
    dc_in_vol: Annotated[int, "I"]
    dc_in_amp: Annotated[int, "I"]
    dc_in_temp: Annotated[int, "H"]
    fan_state: Annotated[int, "B"]
    cfg_ac_enabled: Annotated[int, "B"]
    cfg_ac_xboost: Annotated[int, "B"]
    cfg_ac_out_voltage: Annotated[int, "I"]
    cfg_ac_out_freq: Annotated[int, "B"]
    cfg_ac_work_mode: Annotated[int, "B"]
    cfg_pause_flag: Annotated[int, "B"]
    ac_dip_switch: Annotated[int, "B"]
    cfg_fast_chg_watts: Annotated[int, "H"]
    cfg_slow_chg_watts: Annotated[int, "H"]
    standby_mins: Annotated[int, "H"]
    discharge_type: Annotated[int, "B"]
    ac_passby_auto_en: Annotated[int, "B"]
    pr_balance_mode: Annotated[int, "B"]
    ac_chg_rated_power: Annotated[int, "H"]
    cfg_gfci_enable: Annotated[int, "B"]


class DirectEmsDeltaHeartbeatPack(RawData):
    """EMS Heartbeat (src=0x03, cmdId=0x02)"""
    chg_state: Annotated[int, "B"]
    chg_cmd: Annotated[int, "B"]
    dsg_cmd: Annotated[int, "B"]
    chg_vol: Annotated[int, "I"]
    chg_amp: Annotated[int, "I"]
    fan_level: Annotated[int, "B"]
    max_charge_soc: Annotated[int, "B"]
    bms_model: Annotated[int, "B"]
    lcd_show_soc: Annotated[int, "B"]
    open_ups_flag: Annotated[int, "B"]
    bms_warning_state: Annotated[int, "B"]
    chg_remain_time: Annotated[int, "I"]
    dsg_remain_time: Annotated[int, "I"]
    ems_is_normal_flag: Annotated[int, "B"]
    f32_lcd_show_soc: Annotated[float, "f"]
    bms_is_connt: Annotated[bytes, "3s"]
    max_available_num: Annotated[int, "B"]
    open_bms_idx: Annotated[int, "B"]
    para_vol_min: Annotated[int, "I"]
    para_vol_max: Annotated[int, "I"]
    min_dsg_soc: Annotated[int, "B"]
    open_oil_eb_soc: Annotated[int, "B"]
    close_oil_eb_soc: Annotated[int, "B"]


class DirectBmsMDeltaHeartbeatPack(RawData):
    """BMS Heartbeat (src=0x03 cmdId=0x32 oder src=0x06 cmdId=0x32)"""
    num: Annotated[int, "B"]
    type_: Annotated[int, "B"]
    cell_id: Annotated[int, "B"]
    err_code: Annotated[int, "I"]
    sys_ver: Annotated[int, "I"]
    soc: Annotated[int, "B"]
    vol: Annotated[int, "I"]
    amp: Annotated[int, "I"]
    temp: Annotated[int, "B"]
    open_bms_idx: Annotated[int, "B"]
    design_cap: Annotated[int, "I"]
    remain_cap: Annotated[int, "I"]
    full_cap: Annotated[int, "I"]
    cycles: Annotated[int, "I"]
    soh: Annotated[int, "B"]
    max_cell_vol: Annotated[int, "H"]
    min_cell_vol: Annotated[int, "H"]
    max_cell_temp: Annotated[int, "B"]
    min_cell_temp: Annotated[int, "B"]
    max_mos_temp: Annotated[int, "B"]
    min_mos_temp: Annotated[int, "B"]
    bms_fault: Annotated[int, "B"]
    bq_sys_stat_reg: Annotated[int, "B"]
    tag_chg_amp: Annotated[int, "I"]
    f32_show_soc: Annotated[float, "f"]
    input_watts: Annotated[int, "I"]
    output_watts: Annotated[int, "I"]
    remain_time: Annotated[int, "I"]


# =============================================================================
# Geräteklasse
# =============================================================================

class Delta2Max(EcoFlowDevice):
    """
    EcoFlow Delta 2 Max – BLE-Gerät mit Type7-Verschlüsselung.

    Seriennummer-Präfixe: R351, R354
    Maximale AC-Ladeleistung: 1800 W
    """

    DEVICE_TYPE = "delta2max"
    SERIAL_PREFIX = ["R351", "R354"]
    MAX_AC_CHARGING_POWER = 1800

    def parse_data(self, packet: Packet) -> dict[str, Any]:
        """
        Parsed einen entschlüsselten Packet und gibt MQTT-Datenpunkte zurück.

        Das Routing folgt ha-ef-ble _delta2_base.py data_parse().
        Unbekannte Kombinationen → leeres Dict (kein Fehler).
        """
        src, cmd_set, cmd_id = packet.src, packet.cmdSet, packet.cmdId

        match (src, cmd_set, cmd_id):
            case (0x02, 0x20, 0x02):
                log.debug("[delta2max] PD Heartbeat (src=0x02)")
                return self._parse_pd(
                    Mr350PdHeartbeatDelta2Max.from_bytes(packet.payload))

            case (0x03, 0x03, 0x0E):
                # Kit-Detail-Daten (Extra-Batterien): Struktur noch nicht vollständig
                # implementiert. Vorerst ignorieren – kein Fehler.
                log.debug("[delta2max] Kit-Detail-Paket (0x03/0x03/0x0E) empfangen, "
                          "noch nicht implementiert (payload_len=%d)", len(packet.payload))
                return {}

            case (0x03, 0x20, 0x02):
                log.debug("[delta2max] EMS Heartbeat (src=0x03)")
                return self._parse_ems(
                    DirectEmsDeltaHeartbeatPack.from_bytes(packet.payload))

            case (0x03, 0x20, 0x32):
                log.debug("[delta2max] BMS Main Heartbeat (src=0x03, cmdId=0x32)")
                return self._parse_bms(
                    DirectBmsMDeltaHeartbeatPack.from_bytes(packet.payload))

            case (0x06, 0x20, 0x32):
                log.debug("[delta2max] BMS Extra-Batterie 1 (src=0x06, cmdId=0x32)")
                return self._parse_bms_extra(
                    DirectBmsMDeltaHeartbeatPack.from_bytes(packet.payload))

            case (0x04, _, 0x02):
                log.debug("[delta2max] Inverter Heartbeat (src=0x04, cmdSet=0x%02X)", cmd_set)
                return self._parse_inv(
                    DirectInvDeltaHeartbeatPack.from_bytes(packet.payload))

            case (0x05, 0x20, 0x02):
                log.debug("[delta2max] MPPT Heartbeat (src=0x05)")
                return self._parse_mppt(
                    Mr350MpptHeart.from_bytes(packet.payload))

            case _:
                log.debug("[delta2max] Unbekanntes Paket: src=0x%02X cmdSet=0x%02X cmdId=0x%02X "
                          "payload_len=%d",
                          src, cmd_set, cmd_id, len(packet.payload))
                return {}

    def build_set_command(self, key: str, value: Any) -> Optional[Packet]:
        """
        Baut einen Steuerbefehl-Packet.

        Unterstützte Keys:
          ac_charging_speed      int   1..1800 Watt
          ac_ports               int   0=aus, 1=an
          battery_charge_limit_max  int  50..100 %
          battery_charge_limit_min  int  0..30 %
        """
        try:
            if key == "ac_charging_speed":
                watts = max(1, min(int(value), self.MAX_AC_CHARGING_POWER))
                payload = watts.to_bytes(2, "little") + bytes([0xFF])
                log.debug("[delta2max] Befehl ac_charging_speed=%d W", watts)
                # dst=0x04 (Inverter) – identisch mit ha-ef-ble set_ac_charging_speed()
                return Packet(0x21, 0x04, 0x20, 0x45, payload, version=0x02)

            if key == "ac_ports":
                enabled = 1 if int(value) else 0
                payload = bytes([enabled, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF])
                log.debug("[delta2max] Befehl ac_ports=%d", enabled)
                # dst=0x04 (Inverter) – identisch mit ha-ef-ble enable_ac_ports()
                return Packet(0x21, 0x04, 0x20, 0x42, payload, version=0x02)

            if key == "battery_charge_limit_max":
                limit = max(50, min(100, int(value)))
                log.debug("[delta2max] Befehl battery_charge_limit_max=%d%%", limit)
                return Packet(0x21, 0x03, 0x20, 0x31, bytes([limit]), version=0x02)

            if key == "battery_charge_limit_min":
                limit = max(0, min(30, int(value)))
                log.debug("[delta2max] Befehl battery_charge_limit_min=%d%%", limit)
                return Packet(0x21, 0x03, 0x20, 0x33, bytes([limit]), version=0x02)

            log.warning("[delta2max] Unbekannter Steuerbefehl: key=%s value=%s", key, value)
            return None

        except (TypeError, ValueError) as e:
            log.error("[delta2max] Ungültiger Befehlswert: key=%s value=%r error=%s",
                      key, value, e)
            return None

    def get_initial_requests(self) -> list[Packet]:
        """
        Gibt die Initial-Requests zurück — für die Delta2Max: keine.

        In ha-ef-ble hat _delta2_base kein Äquivalent zu get_initial_requests().
        Das Gerät sendet nach dem Auth SPONTAN Heartbeat-Notifications für alle
        Module (PD, EMS, BMS, INV, MPPT) ohne explizite Anforderung.

        Unsere früheren Versuche (5 Data-Requests, RTC-Sync) haben gezeigt:
        - Data-Requests: Gerät quittiert mit ACK aber sendet dann keine Heartbeats
          und disconnected nach ~6s
        - RTC-Requests (0x52/0x53): Gerät ignoriert sie komplett (kein ACK)

        Fazit: Nichts senden, einfach auf Heartbeats warten.
        """
        return []

    # =========================================================================
    # Parse-Hilfsmethoden
    # =========================================================================

    def _parse_pd(self, hb: Mr350PdHeartbeatDelta2Max) -> dict[str, Any]:
        result = {
            "input_power":              hb.watts_in_sum,
            "output_power":             hb.watts_out_sum,
            "usb_ports":                hb.dc_out_state == 1,
            "usb_a_output_power":       hb.usb1_watt,
            "usb_a_2_output_power":     hb.usb2_watt,
            "usb_c_output_power":       hb.typec1_watts,
            "usb_c_2_output_power":     hb.typec2_watts,
            "dc_12v_port":              hb.car_state == 1,
            "dc_output_power":          hb.car_watts,
            "ac_input_power":           hb.inv_in_watts,
            "ac_output_power":          hb.inv_out_watts,
            "xt60_1_input_power":       hb.pv1_charge_watts,
            "xt60_2_input_power":       hb.pv2_charge_watts,
            "energy_backup":            hb.watthisconfig == 1,
            "energy_backup_battery_level": hb.bp_power_soc,
        }
        log.debug("[delta2max] PD: in=%dW out=%dW soc_backup=%d%%",
                  hb.watts_in_sum, hb.watts_out_sum, hb.bp_power_soc)
        return result

    def _parse_ems(self, hb: DirectEmsDeltaHeartbeatPack) -> dict[str, Any]:
        # f32_lcd_show_soc ist 0.0 wenn nicht gesetzt → Fallback auf lcd_show_soc
        battery_level = (round(hb.f32_lcd_show_soc, 2)
                         if hb.f32_lcd_show_soc else hb.lcd_show_soc)
        result: dict[str, Any] = {
            "battery_level":            battery_level,
            "battery_charge_limit_min": hb.min_dsg_soc,
            "battery_charge_limit_max": hb.max_charge_soc,
        }
        if hb.chg_remain_time:
            result["remaining_time_charging"] = hb.chg_remain_time
        if hb.dsg_remain_time:
            result["remaining_time_discharging"] = hb.dsg_remain_time

        log.debug("[delta2max] EMS: soc=%.1f%% chg_limit=%d%%-%d%%",
                  battery_level, hb.min_dsg_soc, hb.max_charge_soc)
        return result

    def _parse_bms(self, hb: DirectBmsMDeltaHeartbeatPack) -> dict[str, Any]:
        soc = round(hb.f32_show_soc, 2) if hb.f32_show_soc else hb.soc
        result = {
            "battery_level_main":       soc,
            "cell_temperature":         hb.max_cell_temp,
            "battery_input_power":      hb.input_watts,
            "battery_output_power":     hb.output_watts,
            "battery_remaining_time":   hb.remain_time,
        }
        log.debug("[delta2max] BMS Main: soc=%.1f%% temp=%d°C in=%dW out=%dW",
                  soc, hb.max_cell_temp, hb.input_watts, hb.output_watts)
        return result

    def _parse_bms_extra(self, hb: DirectBmsMDeltaHeartbeatPack) -> dict[str, Any]:
        soc = round(hb.f32_show_soc, 2) if hb.f32_show_soc else hb.soc
        result = {
            "battery_1_enabled":            True,
            "battery_1_battery_level":      soc,
            "battery_1_cell_temperature":   hb.max_cell_temp,
        }
        log.debug("[delta2max] BMS Extra-Bat 1: soc=%.1f%% temp=%d°C",
                  soc, hb.max_cell_temp)
        return result

    def _parse_inv(self, hb: DirectInvDeltaHeartbeatPack) -> dict[str, Any]:
        result = {
            "ac_ports":             hb.cfg_ac_enabled == 1,
            "ac_input_voltage":     round(hb.ac_in_vol / 1000, 2),
            "ac_input_current":     round(hb.ac_in_amp / 1000, 2),
            "ac_output_voltage":    round(hb.inv_out_vol / 1000, 2),
            "ac_output_current":    round(hb.inv_out_amp / 1000, 2),
            "ac_charging_speed":    hb.cfg_slow_chg_watts,
        }
        log.debug("[delta2max] INV: ac_ports=%s in=%.1fV/%.2fA out=%.1fV/%.2fA chg=%dW",
                  result["ac_ports"],
                  result["ac_input_voltage"], result["ac_input_current"],
                  result["ac_output_voltage"], result["ac_output_current"],
                  hb.cfg_slow_chg_watts)
        return result

    def _parse_mppt(self, hb: Mr350MpptHeart) -> dict[str, Any]:
        result = {
            "dc_input_voltage":     round(hb.in_vol / 1000, 2),
            "dc_input_current":     round(hb.in_amp / 1000, 2),
            "dc_input_power":       hb.in_watts,
            "dc_input_voltage_2":   round(hb.pv2_in_vol / 1000, 2),
            "dc_input_current_2":   round(hb.pv2_in_amp / 1000, 2),
            "dc_input_power_2":     hb.pv2_in_watts,
            "dc12v_output_voltage": round(hb.car_out_vol / 1000, 2),
            "dc12v_output_current": round(hb.car_out_amp / 1000, 2),
            "dc12v_output_power":   hb.car_out_watts,
        }
        log.debug("[delta2max] MPPT: pv1=%.1fV/%.2fA/%dW pv2=%.1fV/%.2fA/%dW",
                  result["dc_input_voltage"], result["dc_input_current"], hb.in_watts,
                  result["dc_input_voltage_2"], result["dc_input_current_2"], hb.pv2_in_watts)
        return result
