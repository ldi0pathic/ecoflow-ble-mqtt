# =============================================================================
# devices/delta2max.py - EcoFlow Delta 2 Max
# Basierend auf den Paketstrukturen und dem Geräte-Mapping aus ha-ef-ble.
# =============================================================================

from __future__ import annotations

from typing import Annotated, Any, Optional

from protocol import Packet
from .base import EcoFlowDevice
from .rawdata import RawData


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


class Delta2Max(EcoFlowDevice):
    """EcoFlow Delta 2 Max mit aus ha-ef-ble portierten Heartbeat-Strukturen."""

    DEVICE_TYPE = "delta2max"
    SERIAL_PREFIX = ["R351", "R354"]
    MAX_AC_CHARGING_POWER = 1800

    def parse_data(self, packet: Packet) -> dict[str, Any]:
        match (packet.src, packet.cmdSet, packet.cmdId):
            case (0x02, 0x20, 0x02):
                return self._parse_pd(Mr350PdHeartbeatDelta2Max.from_bytes(packet.payload))
            case (0x03, 0x03, 0x0E):
                # In ha-ef-ble werden hier zusätzliche Battery-Kit-Details
                # verarbeitet. Ohne das vollständige Modell können wir das
                # Payload hier noch nicht sauber dekodieren.
                return {}
            case (0x03, 0x20, 0x02):
                return self._parse_ems(DirectEmsDeltaHeartbeatPack.from_bytes(packet.payload))
            case (0x03, 0x20, 0x32):
                return self._parse_bms(DirectBmsMDeltaHeartbeatPack.from_bytes(packet.payload))
            case (0x06, 0x20, 0x32):
                return self._parse_bms_extra(DirectBmsMDeltaHeartbeatPack.from_bytes(packet.payload))
            case (0x04, _, 0x02):
                return self._parse_inv(DirectInvDeltaHeartbeatPack.from_bytes(packet.payload))
            case (0x05, 0x20, 0x02):
                return self._parse_mppt(Mr350MpptHeart.from_bytes(packet.payload))
            case _:
                return {}

    def build_set_command(self, key: str, value: Any) -> Optional[Packet]:
        try:
            if key == "ac_charging_speed":
                watts = max(1, min(int(value), self.MAX_AC_CHARGING_POWER))
                payload = watts.to_bytes(2, "little") + bytes([0xFF])
                return Packet(0x21, 0x05, 0x20, 0x45, payload, version=0x02)

            if key == "ac_ports":
                enabled = 1 if int(value) else 0
                payload = bytes([enabled, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF])
                return Packet(0x21, 0x05, 0x20, 0x42, payload, version=0x02)

            if key == "battery_charge_limit_max":
                limit = max(50, min(100, int(value)))
                return Packet(0x21, 0x03, 0x20, 0x31, bytes([limit]), version=0x02)

            if key == "battery_charge_limit_min":
                limit = max(0, min(30, int(value)))
                return Packet(0x21, 0x03, 0x20, 0x33, bytes([limit]), version=0x02)

            return None
        except (TypeError, ValueError):
            return None

    def get_initial_requests(self) -> list[Packet]:
        return [
            Packet(0x21, 0x02, 0x20, 0x02, b"\x00", version=0x02),
            Packet(0x21, 0x03, 0x20, 0x02, b"\x00", version=0x02),
            Packet(0x21, 0x03, 0x20, 0x32, b"\x00", version=0x02),
            Packet(0x21, 0x04, 0x20, 0x02, b"\x00", version=0x02),
            Packet(0x21, 0x05, 0x20, 0x02, b"\x00", version=0x02),
        ]

    def _parse_pd(self, hb: Mr350PdHeartbeatDelta2Max) -> dict[str, Any]:
        return {
            "input_power": hb.watts_in_sum,
            "output_power": hb.watts_out_sum,
            "usb_ports": hb.dc_out_state == 1,
            "usb_a_output_power": hb.usb1_watt,
            "usb_a_2_output_power": hb.usb2_watt,
            "usb_c_output_power": hb.typec1_watts,
            "usb_c_2_output_power": hb.typec2_watts,
            "dc_12v_port": hb.car_state == 1,
            "dc_output_power": hb.car_watts,
            "ac_input_power": hb.inv_in_watts,
            "ac_output_power": hb.inv_out_watts,
            "xt60_1_input_power": hb.pv1_charge_watts,
            "xt60_2_input_power": hb.pv2_charge_watts,
            "energy_backup": hb.watthisconfig == 1,
            "energy_backup_battery_level": hb.bp_power_soc,
        }

    def _parse_ems(self, hb: DirectEmsDeltaHeartbeatPack) -> dict[str, Any]:
        result = {
            "battery_level": round(hb.f32_lcd_show_soc, 2) if hb.f32_lcd_show_soc else hb.lcd_show_soc,
            "battery_charge_limit_min": hb.min_dsg_soc,
            "battery_charge_limit_max": hb.max_charge_soc,
        }
        if hb.chg_remain_time:
            result["remaining_time_charging"] = hb.chg_remain_time
        if hb.dsg_remain_time:
            result["remaining_time_discharging"] = hb.dsg_remain_time
        return result

    def _parse_bms(self, hb: DirectBmsMDeltaHeartbeatPack) -> dict[str, Any]:
        return {
            "battery_level_main": round(hb.f32_show_soc, 2) if hb.f32_show_soc else hb.soc,
            "cell_temperature": hb.max_cell_temp,
            "battery_input_power": hb.input_watts,
            "battery_output_power": hb.output_watts,
            "battery_remaining_time": hb.remain_time,
        }

    def _parse_bms_extra(self, hb: DirectBmsMDeltaHeartbeatPack) -> dict[str, Any]:
        return {
            "battery_1_enabled": True,
            "battery_1_battery_level": round(hb.f32_show_soc, 2) if hb.f32_show_soc else hb.soc,
            "battery_1_cell_temperature": hb.max_cell_temp,
        }

    def _parse_inv(self, hb: DirectInvDeltaHeartbeatPack) -> dict[str, Any]:
        return {
            "ac_ports": hb.cfg_ac_enabled == 1,
            "ac_input_voltage": round(hb.ac_in_vol / 1000, 2),
            "ac_input_current": round(hb.ac_in_amp / 1000, 2),
            "ac_output_voltage": round(hb.inv_out_vol / 1000, 2),
            "ac_output_current": round(hb.inv_out_amp / 1000, 2),
            "ac_charging_speed": hb.cfg_slow_chg_watts,
        }

    def _parse_mppt(self, hb: Mr350MpptHeart) -> dict[str, Any]:
        return {
            "dc_input_voltage": round(hb.in_vol / 1000, 2),
            "dc_input_current": round(hb.in_amp / 1000, 2),
            "dc_input_power": hb.in_watts,
            "dc_input_voltage_2": round(hb.pv2_in_vol / 1000, 2),
            "dc_input_current_2": round(hb.pv2_in_amp / 1000, 2),
            "dc_input_power_2": hb.pv2_in_watts,
            "dc12v_output_voltage": round(hb.car_out_vol / 1000, 2),
            "dc12v_output_current": round(hb.car_out_amp / 1000, 2),
            "dc12v_output_power": hb.car_out_watts,
        }
