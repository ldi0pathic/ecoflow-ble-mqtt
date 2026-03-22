# =============================================================================
# mqtt_bridge.py - MQTT Anbindung
# Veröffentlicht Gerätedaten und empfängt Steuerbefehle
#
# Topics (Beispiel für PowerStream):
#   Lesen:    ecoflow/powerstream_800w/pv1_input_watts   → "245.3"
#             ecoflow/powerstream_800w/battery_soc        → "78"
#   Steuern:  ecoflow/powerstream_800w/set/permanent_watts ← "600"
#   Status:   ecoflow/powerstream_800w/status             → "online" / "offline"
# =============================================================================

import json
import logging
import threading
from typing import Optional, Callable

import paho.mqtt.client as mqtt

log = logging.getLogger(__name__)


class MQTTBridge:
    """
    Verwaltet die MQTT-Verbindung und das Topic-Routing.
    Läuft in einem eigenen Thread (paho ist blocking).
    """

    def __init__(self, host: str, port: int, base_topic: str,
                 user: str = "", password: str = ""):
        self._host       = host
        self._port       = port
        self._base_topic = base_topic.rstrip("/")
        self._client     = mqtt.Client(client_id="ecoflow-ble-gateway", clean_session=True)
        self._connected  = False

        # Callbacks für eingehende Set-Befehle: {device_name: callback}
        self._set_callbacks: dict[str, Callable[[str, str], None]] = {}

        if user:
            self._client.username_pw_set(user, password)

        self._client.on_connect    = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message    = self._on_message

    # --- Starten / Stoppen ---------------------------------------------------

    def start(self):
        """Verbindet mit Broker und startet Loop in eigenem Thread."""
        log.info("Verbinde mit MQTT Broker %s:%d ...", self._host, self._port)
        self._client.connect_async(self._host, self._port, keepalive=60)
        self._client.loop_start()

    def stop(self):
        self._client.loop_stop()
        self._client.disconnect()

    # --- Gerät registrieren --------------------------------------------------

    def register_device(self, device_name: str,
                        on_set_command: Callable[[str, str], None]):
        """
        Registriert ein Gerät und abonniert sein Set-Topic.
        on_set_command(key, value_str) wird aufgerufen wenn ein Befehl ankommt.
        """
        self._set_callbacks[device_name] = on_set_command
        set_topic = f"{self._base_topic}/{device_name}/set/#"
        if self._connected:
            self._client.subscribe(set_topic)
            log.info("Abonniert: %s", set_topic)

    # --- Daten veröffentlichen -----------------------------------------------

    def publish_state(self, device_name: str, state: dict):
        """Veröffentlicht alle geänderten Datenpunkte eines Geräts."""
        if not self._connected:
            return
        for key, value in state.items():
            topic = f"{self._base_topic}/{device_name}/{key}"
            payload = str(round(value, 2)) if isinstance(value, float) else str(value)
            self._client.publish(topic, payload, retain=True)
            log.debug("→ MQTT %s = %s", topic, payload)

    def publish_status(self, device_name: str, status: str):
        """Veröffentlicht den Verbindungsstatus (online/offline)."""
        topic = f"{self._base_topic}/{device_name}/status"
        self._client.publish(topic, status, retain=True)
        log.info("[%s] Status: %s", device_name, status)

    def publish_json(self, device_name: str, state: dict):
        """Veröffentlicht alle Werte zusätzlich als JSON-Objekt (praktisch für ioBroker)."""
        topic = f"{self._base_topic}/{device_name}/json"
        self._client.publish(topic, json.dumps(state), retain=True)

    # --- MQTT Callbacks ------------------------------------------------------

    def _on_connect(self, client, _userdata, _flags, rc):
        if rc == 0:
            self._connected = True
            log.info("✓ MQTT verbunden mit %s:%d", self._host, self._port)
            # Alle registrierten Geräte abonnieren
            for device_name in self._set_callbacks:
                topic = f"{self._base_topic}/{device_name}/set/#"
                client.subscribe(topic)
                log.info("Abonniert: %s", topic)
        else:
            log.error("MQTT Verbindung fehlgeschlagen: rc=%d", rc)

    def _on_disconnect(self, _client, _userdata, rc):
        self._connected = False
        if rc != 0:
            log.warning("MQTT getrennt (rc=%d), paho reconnectet automatisch...", rc)

    def _on_message(self, _client, _userdata, msg):
        """Verarbeitet eingehende Set-Befehle."""
        # Topic: ecoflow/<device_name>/set/<key>
        parts = msg.topic.split("/")
        if len(parts) < 4 or parts[-2] != "set":
            # Neues Format: ecoflow/<device>/set/<key>
            # parts: ["ecoflow", "powerstream_800w", "set", "permanent_watts"]
            pass

        try:
            # Gerätename aus Topic extrahieren
            # base_topic kann Slashes enthalten → relativ zum Base zählen
            base_parts = self._base_topic.split("/")
            relative   = parts[len(base_parts):]  # ["powerstream_800w", "set", "permanent_watts"]

            if len(relative) < 3 or relative[1] != "set":
                return

            device_name = relative[0]
            key         = "/".join(relative[2:])   # Für verschachtelte Keys
            
            if key.endswith("/set"):
                key = key[:-4]
                
            value       = msg.payload.decode("utf-8").strip()

            log.info("[%s] Set-Befehl empfangen: %s = %s", device_name, key, value)

            callback = self._set_callbacks.get(device_name)
            if callback:
                callback(key, value)
            else:
                log.warning("Unbekanntes Gerät in Set-Topic: %s", device_name)

        except Exception as e:
            log.error("Fehler bei Set-Befehl: %s", e)
