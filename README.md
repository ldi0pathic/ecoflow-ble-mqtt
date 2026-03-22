# EcoFlow BLE → MQTT Gateway

Verbindet EcoFlow Geräte per Bluetooth Low Energy (BLE) direkt mit einem MQTT Broker — **ohne Cloud, ohne Internet**.

Inspiriert von und basierend auf dem Protokoll aus [ha-ef-ble](https://github.com/rabits/ha-ef-ble) von [@rabits](https://github.com/rabits) (Apache-2.0).

## Unterstützte Geräte

| Gerät            | Status         |
|------------------|----------------|
| PowerStream 800W | ✅ Vollständig |
| PowerStream 600W | ⚠️ Ungetestet  |
| Delta 2          | 🔜 Geplant     |
| Delta 2 Max      | ✅ Basis-Support |

> **Hinweis:** PowerStream 600W sollte funktionieren da es das gleiche Protokoll nutzt, wurde aber noch nicht getestet. Feedback willkommen!

## Voraussetzungen

- Raspberry Pi 3 oder neuer (mit eingebautem Bluetooth)
- Python 3.11+
- MQTT Broker (z.B. Mosquitto oder ioBroker MQTT Adapter)

## Installation
```bash
git clone https://github.com/DEINNAME/ecoflow-ble-mqtt.git
cd ecoflow-ble-mqtt
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config.example.py config.py
nano config.py  # MQTT-IP und User-ID eintragen
```

> **Tipp für Raspberry Pi:** Dateilogging ist optional. Wenn du keine feste Log-Datei willst, lass `LOG_FILE` leer und nutze nur `journalctl`/Stdout.

## Konfiguration

In `config.py`:
```python
MQTT_HOST = "192.168.x.x"   # IP deines MQTT Brokers
DEVICES = [
    {
        "type":    "powerstream",
        "name":    "powerstream_800w",
        "address": "",         # BLE MAC oder leer für automatischen Scan
        "user_id": 0,          # EcoFlow User-ID (App → Profil → Einstellungen)
    },
    {
        "type":    "delta2max",
        "name":    "delta2_max",
        "address": "",         # leer = Auto-Erkennung per Serienpräfix R351/R354
        "user_id": 0,
    },
]

BLE_SCAN_TIMEOUT = 30
LOG_FILE = ""  # optional, z.B. /var/log/ecoflow-ble.log
```

## MQTT Topics

### Lesen
```
ecoflow/powerstream_800w/pv_power_1        # PV Panel 1 (W)
ecoflow/powerstream_800w/pv_power_2        # PV Panel 2 (W)
ecoflow/powerstream_800w/inverter_power    # Aktuelle Einspeisung (W)
ecoflow/powerstream_800w/battery_level     # Batteriestand (%)
ecoflow/powerstream_800w/battery_power     # Batterie Leistung (W)
ecoflow/powerstream_800w/load_power        # Aktueller Einstellwert (W)

ecoflow/delta2_max/battery_level           # Batteriestand (%)
ecoflow/delta2_max/input_power             # Gesamte Eingangsleistung (W)
ecoflow/delta2_max/output_power            # Gesamte Ausgangsleistung (W)
ecoflow/delta2_max/ac_input_power          # AC-Ladeleistung (W)
ecoflow/delta2_max/ac_output_power         # AC-Ausgangsleistung (W)
ecoflow/delta2_max/xt60_1_input_power      # Solar Eingang 1 (W)
ecoflow/delta2_max/xt60_2_input_power      # Solar Eingang 2 (W)
```

### Steuern
```
ecoflow/powerstream_800w/set/load_power            # Einspeiseleistung setzen (0-800W)
ecoflow/delta2_max/set/ac_charging_speed           # AC-Ladeleistung setzen (1-1800W)
ecoflow/delta2_max/set/ac_ports                    # AC-Ausgänge 0/1
ecoflow/delta2_max/set/battery_charge_limit_min    # Minimaler SoC (0-30)
ecoflow/delta2_max/set/battery_charge_limit_max    # Maximaler SoC (50-100)
```

## Autostart
```bash
sudo cp ecoflow-ble.service.example /etc/systemd/system/ecoflow-ble.service
# User und Pfade in der Service-Datei anpassen
sudo systemctl enable ecoflow-ble
sudo systemctl start ecoflow-ble
```

## Entstehung

100% **Vibe Coded** mit [Claude](https://claude.ai) 🤖  
Kein Plan, kein Problem — einfach fragen bis es läuft. ⚡

## Credits

- [ha-ef-ble](https://github.com/rabits/ha-ef-ble) — EcoFlow BLE Protokoll Reverse Engineering und Home Assistant Integration

## Delta 2 Max Hinweise

Die Delta 2 Max Unterstützung orientiert sich an den bekannten `ha-ef-ble`-Strukturen für die Serienpräfixe `R351` und `R354`. Implementiert sind die wichtigsten Telemetrie-Heartbeats sowie Basis-Steuerbefehle für AC-Ausgänge, AC-Ladeleistung und Ladegrenzen. Zusätzliche Felder oder modellabhängige Abweichungen können je nach Firmware noch fehlen.
