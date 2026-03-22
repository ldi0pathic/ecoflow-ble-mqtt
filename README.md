# EcoFlow BLE → MQTT Gateway

Verbindet EcoFlow Geräte per Bluetooth Low Energy (BLE) direkt mit einem MQTT Broker — **ohne Cloud, ohne Internet**.

Inspiriert von und basierend auf dem Protokoll aus [ha-ef-ble](https://github.com/rabits/ha-ef-ble) von [@rabits](https://github.com/rabits) (Apache-2.0).

## Unterstützte Geräte

| Gerät            | Status         |
|------------------|----------------|
| PowerStream 800W | ✅ Vollständig |
| PowerStream 600W | ⚠️ Ungetestet  |
| Delta 2          | 🔜 Geplant     |
| Delta 2 Max      | 🔜 Geplant     |

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
]
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
```

### Steuern
```
ecoflow/powerstream_800w/set/load_power    # Einspeiseleistung setzen (0-800W)
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