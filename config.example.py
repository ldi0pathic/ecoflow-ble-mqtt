# =============================================================================
# config.py - Zentrale Konfiguration
# Hier trägst du deine Geräte und MQTT-Einstellungen ein
# =============================================================================

# --- MQTT Broker 
MQTT_HOST     = "192.168.x.x"   
MQTT_PORT     = 1883
MQTT_USER     = ""                
MQTT_PASSWORD = ""
MQTT_BASE_TOPIC = "ecoflow"       # Topics werden: ecoflow/<gerät>/<datenpunkt>

# --- Deine EcoFlow Geräte ----------------------------------------------------
# user_id: aus der EcoFlow App (Profil → Einstellungen → Benutzer-ID)
# address: BLE MAC-Adresse des Geräts (leer lassen → automatisches Scannen)
DEVICES = [
    {
        "type":    "powerstream",
        "name":    "powerstream_800w",     # frei wählbar, wird Teil des MQTT-Topics
        "address": "",                     # z.B. "AA:BB:CC:DD:EE:FF"
        "user_id": 123456,              # deine EcoFlow User-ID 
    },
]

# --- BLE Einstellungen -------------------------------------------------------
BLE_SCAN_TIMEOUT      = 30    # Sekunden für den initialen Scan
BLE_RECONNECT_DELAY   = 10    # Sekunden zwischen Wiederverbindungsversuchen
BLE_CONNECT_TIMEOUT   = 20    # Sekunden bis Verbindungsabbruch

# --- Logging -----------------------------------------------------------------
LOG_LEVEL = "INFO"   # DEBUG, INFO, WARNING, ERROR
