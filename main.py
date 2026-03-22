#!/usr/bin/env python3
# =============================================================================
# main.py - EcoFlow BLE → MQTT Gateway
# Startet alle konfigurierten Geräte und die MQTT-Bridge
#
# Starten:  python3 main.py
# Als Service: siehe ecoflow-ble.service
# =============================================================================

import asyncio
import logging
import signal
import sys

import config
from devices import create_device
from ble_manager import BLEDeviceManager
from mqtt_bridge import MQTTBridge

# --- Logging einrichten ------------------------------------------------------
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("/home/andre/logs/ecoflow-ble.log"),
    ]
)
log = logging.getLogger("main")


# =============================================================================
# Gateway - verbindet BLE Manager mit MQTT Bridge
# =============================================================================

class EcoFlowGateway:

    def __init__(self):
        self._mqtt    = MQTTBridge(
            host       = config.MQTT_HOST,
            port       = config.MQTT_PORT,
            base_topic = config.MQTT_BASE_TOPIC,
            user       = config.MQTT_USER,
            password   = config.MQTT_PASSWORD,
        )
        self._ble_managers: list[BLEDeviceManager] = []

    def setup(self):
        """Erstellt alle Geräte und verbindet MQTT mit BLE."""
        for device_cfg in config.DEVICES:
            try:
                device = create_device(device_cfg)
                log.info("Gerät konfiguriert: %s (%s)", device.name, device.DEVICE_TYPE)

                # BLE Manager für dieses Gerät
                ble_mgr = BLEDeviceManager(
                    device          = device,
                    reconnect_delay = config.BLE_RECONNECT_DELAY,
                    connect_timeout = config.BLE_CONNECT_TIMEOUT,
                )

                # State-Änderungen → MQTT
                def make_state_callback(mgr, dev):
                    def on_state(device_name: str, changed: dict):
                        self._mqtt.publish_state(device_name, changed)
                        self._mqtt.publish_json(device_name, dev.get_state())
                    return on_state

                device.set_state_callback(make_state_callback(ble_mgr, device))

                # MQTT Set-Befehle → BLE
                def make_set_callback(mgr, dev):
                    def on_set(key: str, value_str: str):
                        try:
                            # Wert in passenden Typ konvertieren
                            try:
                                value = int(value_str)
                            except ValueError:
                                value = float(value_str)

                            payload = dev.build_set_command(key, value)
                            if payload:
                                mgr.enqueue_command(payload)
                                log.info("[%s] Befehl eingereiht: %s = %s",
                                         dev.name, key, value)
                        except Exception as e:
                            log.error("[%s] Set-Fehler: %s", dev.name, e)
                    return on_set

                self._mqtt.register_device(device.name, make_set_callback(ble_mgr, device))
                self._ble_managers.append(ble_mgr)

            except Exception as e:
                log.error("Fehler beim Einrichten von Gerät %s: %s",
                          device_cfg.get("name", "?"), e)

    async def run(self):
        """Startet MQTT und alle BLE Manager."""
        self._mqtt.start()

        # Alle BLE Manager parallel starten
        tasks = [asyncio.create_task(mgr.run()) for mgr in self._ble_managers]

        if not tasks:
            log.error("Keine Geräte konfiguriert! Bitte config.py anpassen.")
            return

        log.info("Gateway gestartet mit %d Gerät(en)", len(tasks))

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            log.info("Gateway wird gestoppt...")
            for mgr in self._ble_managers:
                mgr.stop()
            self._mqtt.stop()

    def stop(self):
        for mgr in self._ble_managers:
            mgr.stop()
        self._mqtt.stop()


# =============================================================================
# Entry Point
# =============================================================================

async def main():
    gateway = EcoFlowGateway()
    gateway.setup()

    # Graceful Shutdown bei SIGINT / SIGTERM
    loop = asyncio.get_running_loop()

    def shutdown(_signum, _frame):
        log.info("Signal empfangen, stoppe...")
        gateway.stop()
        for task in asyncio.all_tasks(loop):
            task.cancel()

    signal.signal(signal.SIGINT,  shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    await gateway.run()


if __name__ == "__main__":
    log.info("=" * 60)
    log.info("EcoFlow BLE → MQTT Gateway")
    log.info("=" * 60)
    asyncio.run(main())
