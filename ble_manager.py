# =============================================================================
# ble_manager.py - BLE Verbindung + Auth Handshake (portiert von ha-ef-ble)
# Unterstützt encrypt_type 1 (PowerStream) und 7 (Delta2, Delta2Max etc.)
# =============================================================================

import asyncio
import logging
import time
import struct
from typing import Optional, Any

from bleak import BleakClient, BleakScanner

from protocol import (
    UUID_NOTIFY, UUID_WRITE,
    Packet, crc8,
    encode_simple, parse_simple,
    Type1Crypto, Type7Crypto,
    build_auth_md5,
)
from devices.base import EcoFlowDevice

log = logging.getLogger(__name__)

# Manufacturer ID für EcoFlow
EF_MANUFACTURER_ID = 0xB5B5

# Mindestabstand zwischen zwei aufeinanderfolgenden Poll-Requests (Sekunden).
# Zu niedrig → Gerät antwortet nicht mehr / BLE-Stack überflutet.
# ha-ef-ble sendet Initial-Requests NUR einmal nach Auth; das Gerät schickt
# danach selbständig Heartbeats. Wir tun das Gleiche: einmalig alle Requests
# senden, dann nur noch auf eingehende Notifications hören.
_INITIAL_REQUEST_MIN_INTERVAL = 0.35   # Pause zwischen den einzelnen Requests
_INITIAL_REQUEST_SEND_TIMEOUT = 30.0  # Nach Auth: Requests innerhalb dieser Zeit senden

# Keepalive: ha-ef-ble sendet alle 30s einen Auth-Status-Request damit das Gerät
# die Verbindung nicht wegen Inaktivität trennt. Beobachtet: Delta2Max trennt
# nach ~7s wenn nichts gesendet wird.
_KEEPALIVE_INTERVAL = 20.0  # Sekunden zwischen Keepalive-Paketen (konservativ 20s)


def _is_bluez_in_progress_error(exc: Exception) -> bool:
    return "org.bluez.Error.InProgress" in str(exc)


def _extract_type7_status(payload: bytes) -> int:
    """
    Type7 Simple-Responses tragen den eigentlichen Status nicht immer an Stelle 0.

    Beobachtete Frames wie `f0 00` nutzen ein führendes Response-/Opcode-Byte und
    legen den Erfolgsstatus erst dahinter ab.
    """
    if not payload:
        raise ValueError("empty Type7 status payload")
    if len(payload) >= 2 and payload[0] in {0xF0, 0xF1}:
        return payload[1]
    return payload[-1]


def _copy_log(level: int, msg: str, *args):
    """[COPY] Logging-Wrapper – diese Einträge sind für Debug-Sitzungen gedacht."""
    log.log(level, "[COPY] " + msg, *args)


def _get_encrypt_type(manufacturer_data: dict) -> int:
    """Liest encrypt_type aus BLE Advertisement Manufacturer Data."""
    data = manufacturer_data.get(EF_MANUFACTURER_ID, b"")
    if len(data) > 22:
        capability_flags = data[22]
        return (capability_flags & 0b0111000) >> 3
    # Fallback: Type7 für unbekannte Geräte
    return 7


def _get_serial(manufacturer_data: dict) -> str:
    """Liest Seriennummer aus BLE Advertisement."""
    data = manufacturer_data.get(EF_MANUFACTURER_ID, b"")
    if len(data) >= 17:
        return data[1:17].decode("ascii", errors="ignore").rstrip("\x00")
    return ""


class BLEDeviceManager:
    """
    Verwaltet die BLE-Verbindung zu einem einzelnen EcoFlow-Gerät.
    Implementiert den korrekten mehrstufigen Auth-Handshake aus ha-ef-ble.

    Auth-Ablauf für Type7 (Delta2, Delta2Max):
      1. Public Key Exchange (SECP160r1)
      2. Key Info Request → Session Key
      3. Auth Status Request
      4. MD5 Authentication

    Nach erfolgreicher Auth:
      - Initial-Requests werden EINMALIG gesendet (ein Request pro Tick,
        mit _INITIAL_REQUEST_MIN_INTERVAL Pause dazwischen).
      - Das Gerät schickt danach selbständig Heartbeat-Notifications.
      - Keine periodischen Polls nötig – nur auf Notifications hören.

    Auth-Ablauf für Type1 (PowerStream):
      1. Session Header senden (ECIES Curve25519)
      2. MD5 Authentication direkt
    """

    def __init__(self, device: EcoFlowDevice, reconnect_delay: int = 10,
                 connect_timeout: int = 20, scan_timeout: int = 30,
                 notify_queue_size: int = 128):
        self._device          = device
        self._reconnect_delay = reconnect_delay
        self._connect_timeout = connect_timeout
        self._scan_timeout    = scan_timeout
        self._client          : Optional[BleakClient] = None
        self._authenticated   = False
        self._running         = False
        self._send_queue      : asyncio.Queue = asyncio.Queue()
        self._encrypt_type    = 7   # wird beim Scan ermittelt
        self._serial          = ""  # Seriennummer vom Gerät
        self._crypto          = None
        self._rx_buffer       = bytearray()
        self._auth_buffer     = bytearray()
        self._notify_queue    : asyncio.Queue[bytes] = asyncio.Queue(maxsize=notify_queue_size)
        self._notify_task     : Optional[asyncio.Task] = None
        # State-Machine für Auth
        self._auth_state      = "idle"
        self._seq_counter     = 0

        # --- Initial-Request-Versand (einmalig nach Auth) ---
        # _initial_requests_sent: True sobald alle Requests einmal gesendet wurden.
        # _initial_request_index: Index des nächsten zu sendenden Requests.
        # _next_initial_at: Monotonic-Timestamp; vor diesem Zeitpunkt keinen Request
        #                   senden (Mindestabstand zwischen Requests).
        self._initial_requests_sent  = False
        self._initial_request_index  = 0
        self._next_initial_at        = 0.0

        # --- Keepalive (verhindert Disconnect wegen Inaktivität) ---
        self._next_keepalive_at      = 0.0

    # =========================================================================
    # Hauptschleife
    # =========================================================================

    async def run(self):
        self._running = True
        log.info("[%s] BLE Manager gestartet", self._device.name)

        while self._running:
            try:
                ble_address, adv_data = await self._resolve_address()
                if not ble_address:
                    log.warning("[%s] Gerät nicht gefunden, warte %ds...",
                                self._device.name, self._reconnect_delay)
                    await asyncio.sleep(self._reconnect_delay)
                    continue

                log.info("[%s] Verbinde mit %s (encrypt_type=%d, serial=%s)...",
                         self._device.name, ble_address, self._encrypt_type, self._serial)

                try:
                    async with BleakClient(
                        ble_address,
                        timeout=self._connect_timeout,
                        disconnected_callback=self._on_disconnect,
                    ) as client:
                        self._client        = client
                        self._authenticated = False
                        self._rx_buffer     = bytearray()
                        self._auth_buffer   = bytearray()
                        self._auth_state    = "idle"
                        self._seq_counter   = 0
                        self._initial_requests_sent = False
                        self._initial_request_index = 0
                        self._next_initial_at       = 0.0
                        self._next_keepalive_at     = 0.0

                        if self._encrypt_type == 1:
                            self._crypto = Type1Crypto(self._serial)
                        else:
                            self._crypto = Type7Crypto()

                        log.info("[%s] BLE verbunden", self._device.name)

                        # MTU: BlueZ handelt sie automatisch beim Verbinden aus.
                        # _acquire_mtu() wird NICHT aufgerufen: es öffnet einen
                        # AcquireNotify-Handle der mit start_notify() kollidiert
                        # → "Unexpected EOF" nach 8s → Disconnect.
                        log.debug("[%s] MTU: %s bytes (BlueZ automatisch)",
                                  self._device.name,
                                  getattr(client, "mtu_size", "?"))

                        self._notify_queue = asyncio.Queue(maxsize=self._notify_queue.maxsize)
                        self._notify_task = asyncio.create_task(self._process_notify_queue())
                        await client.start_notify(UUID_NOTIFY, self._on_notify)

                        # Service Changed Indication (UUID 00002a05) abonnieren.
                        # Das Gerät sendet nach dem Auth eine Service Changed
                        # INDICATION und wartet auf eine ATT Confirmation.
                        # bleak sendet diese automatisch wenn start_notify
                        # auf der Characteristic aufgerufen wird.
                        # Ohne Subscription: kein Confirm → Gerät disconnected nach 8s.
                        UUID_SERVICE_CHANGED = "00002a05-0000-1000-8000-00805f9b34fb"
                        try:
                            svc_char = client.services.get_characteristic(UUID_SERVICE_CHANGED)
                            if svc_char:
                                await client.start_notify(UUID_SERVICE_CHANGED,
                                                          self._on_service_changed)
                                log.debug("[%s] Service Changed Indication abonniert",
                                          self._device.name)
                                _copy_log(logging.DEBUG,
                                          "[%s] start_notify auf Service Changed (00002a05) OK",
                                          self._device.name)
                            else:
                                log.debug("[%s] Service Changed Characteristic nicht gefunden",
                                          self._device.name)
                        except Exception as e:
                            log.warning("[%s] Service Changed Subscription fehlgeschlagen: %s",
                                        self._device.name, e)

                        await self._start_auth(client)

                        while self._running and client.is_connected:
                            # Ausstehende Steuerbefehle senden
                            try:
                                packet = self._send_queue.get_nowait()
                                encoded = self._crypto.encode_packet(packet)
                                await self._write(client, encoded)
                            except asyncio.QueueEmpty:
                                pass

                            # Initial-Requests einmalig nach Auth senden
                            if self._authenticated and not self._initial_requests_sent:
                                await self._send_next_initial_request(client)

                            # Keepalive NUR für Type1 (PowerStream).
                            # Type7-Geräte (Delta2Max etc.) senden selbständig
                            # Heartbeats – ein 0x89-Paket löst dort einen neuen
                            # Auth-Handshake aus statt als Ping zu wirken.
                            if self._authenticated and self._encrypt_type == 1:
                                await self._send_keepalive_if_due(client)

                            await asyncio.sleep(0.1)

                except EOFError:
                    log.warning("[%s] D-Bus Fehler, reconnecte...", self._device.name)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    log.error("[%s] BLE Fehler: %s", self._device.name, e)
                finally:
                    await self._stop_notify_task()
                    self._client = None

            except asyncio.CancelledError:
                break
            except Exception as e:
                if _is_bluez_in_progress_error(e):
                    log.warning("[%s] BlueZ ist beschäftigt (%s), versuche es gleich erneut...",
                                self._device.name, e)
                    await asyncio.sleep(1)
                    continue
                log.error("[%s] Fehler: %s", self._device.name, e)

            if self._running:
                log.info("[%s] Reconnect in %ds...",
                         self._device.name, self._reconnect_delay)
                await asyncio.sleep(self._reconnect_delay)

        log.info("[%s] BLE Manager gestoppt", self._device.name)

    def stop(self):
        self._running = False

    def enqueue_command(self, packet: Packet):
        """Fügt ein Packet in die Sendewarteschlange ein."""
        if not self._authenticated:
            log.warning("[%s] Nicht authentifiziert, Befehl verworfen",
                        self._device.name)
            return
        self._send_queue.put_nowait(packet)

    # =========================================================================
    # Initial-Requests (einmalig nach Auth, nicht periodisch)
    # =========================================================================

    async def _send_next_initial_request(self, client: BleakClient):
        """
        Sendet die Initial-Requests des Geräts EINMALIG nach der Authentifizierung.

        Das Gerät antwortet auf jeden Request mit einem Notification-Paket und
        sendet danach von selbst periodische Heartbeats. Es gibt keinen Grund,
        die Requests zu wiederholen – das würde den BLE-Stack überlasten.

        Zwischen zwei aufeinanderfolgenden Requests wird _INITIAL_REQUEST_MIN_INTERVAL
        Sekunden gewartet (Rate-Limiting auf dem Gerät).
        """
        requests = self._device.get_initial_requests()
        if not requests:
            self._initial_requests_sent = True
            return

        now = time.monotonic()
        if now < self._next_initial_at:
            return

        if self._initial_request_index >= len(requests):
            # Alle Requests wurden gesendet
            self._initial_requests_sent = True
            log.info("[%s] Alle %d Initial-Requests gesendet, warte auf Heartbeats",
                     self._device.name, len(requests))
            _copy_log(logging.INFO,
                      "[%s] Initial-Request-Phase abgeschlossen (alle %d Requests gesendet)",
                      self._device.name, len(requests))
            return

        packet = requests[self._initial_request_index]
        encoded = self._crypto.encode_packet(packet)

        log.debug("[%s] Sende Initial-Request %d/%d: dst=0x%02X cmdSet=0x%02X cmdId=0x%02X",
                  self._device.name,
                  self._initial_request_index + 1, len(requests),
                  packet.dst, packet.cmdSet, packet.cmdId)
        _copy_log(logging.DEBUG,
                  "[%s] Initial-Request %d/%d: dst=0x%02X cmdSet=0x%02X cmdId=0x%02X encoded=%s",
                  self._device.name,
                  self._initial_request_index + 1, len(requests),
                  packet.dst, packet.cmdSet, packet.cmdId,
                  encoded.hex())

        if await self._write(client, encoded):
            self._initial_request_index += 1
            self._next_initial_at = now + _INITIAL_REQUEST_MIN_INTERVAL
        else:
            # Schreibfehler: kurze Pause, dann nochmal versuchen
            log.warning("[%s] Initial-Request %d fehlgeschlagen, Wiederholung in 1s",
                        self._device.name, self._initial_request_index + 1)
            self._next_initial_at = now + 1.0

    async def _mark_authenticated(self):
        """Setzt den Auth-State und bereitet den Initial-Request-Versand vor."""
        self._authenticated          = True
        self._auth_state             = "authenticated"
        self._initial_requests_sent  = False
        self._initial_request_index  = 0
        self._next_initial_at        = 0.0
        self._next_keepalive_at      = time.monotonic() + _KEEPALIVE_INTERVAL
        log.info("[%s] Authentifizierung erfolgreich, starte Initial-Request-Phase",
                 self._device.name)

    async def _send_keepalive_if_due(self, client: BleakClient):
        """
        Sendet einen Keepalive-Packet wenn das Intervall abgelaufen ist.

        ha-ef-ble (powerstream.py) sendet alle 30s ein Auth-Status-Packet (0x89)
        damit das Gerät die Verbindung nicht wegen Inaktivität trennt.
        Beobachtet: Delta2Max trennt nach ~7s ohne Aktivität.
        Wir verwenden 20s Intervall als sichere Marge.

        Das Auth-Status-Packet (cmdSet=0x35, cmdId=0x89) ist ein bekanntes
        "Ping" im EcoFlow-Protokoll – das Gerät antwortet mit einem Heartbeat.
        """
        now = time.monotonic()
        if now < self._next_keepalive_at:
            return

        # Auth-Status-Packet als Keepalive senden
        # Identisch mit ha-ef-ble Connection.send_auth_status_packet()
        packet = Packet(0x21, 0x35, 0x35, 0x89, b"", 0x01, 0x01, 0x13)
        encoded = self._crypto.encode_packet(packet)

        log.debug("[%s] Sende Keepalive (Auth-Status-Packet)", self._device.name)
        _copy_log(logging.DEBUG,
                  "[%s] Keepalive gesendet: encoded=%s",
                  self._device.name, encoded.hex())

        if await self._write(client, encoded):
            self._next_keepalive_at = now + _KEEPALIVE_INTERVAL
        else:
            # Bei Fehler kürzere Wartezeit
            self._next_keepalive_at = now + 5.0
            log.warning("[%s] Keepalive fehlgeschlagen", self._device.name)

    # =========================================================================
    # Auth Handshake
    # =========================================================================

    async def _start_auth(self, client: BleakClient):
        if self._encrypt_type == 1:
            await self._auth_type1(client)
        else:
            await self._auth_type7_step1(client)

    def _next_seq(self) -> bytes:
        self._seq_counter = (self._seq_counter + 1) & 0xFFFFFFFF
        if self._seq_counter == 0:
            self._seq_counter = 1
        return self._seq_counter.to_bytes(4, "little")

    async def _auth_type1(self, client: BleakClient):
        """Type1: Key aus Seriennummer, dann Auth Status + MD5"""
        self._crypto = Type1Crypto(self._serial)
        self._auth_state = "type1_auth_sent"

        log.debug("[%s] Type1: starte Auth (serial=%s)", self._device.name, self._serial)

        # Schritt 1: Auth Status Packet (cmd_id=0x89)
        pkt_status = Packet(0x21, 0x35, 0x35, 0x89, b"", 0x01, 0x01, 0x13,
                            seq=self._next_seq())
        await self._write(client, self._crypto.encode_packet(pkt_status))
        await asyncio.sleep(0.3)

        # Schritt 2: MD5 Auth Packet (cmd_id=0x86)
        md5_payload = build_auth_md5(str(self._device.user_id), self._serial)
        pkt_auth = Packet(0x21, 0x35, 0x35, 0x86, md5_payload, 0x01, 0x01, 0x13,
                          seq=self._next_seq())
        await self._write(client, self._crypto.encode_packet(pkt_auth))

        _copy_log(logging.DEBUG,
                  "[%s] Type1 Auth-Paket gesendet: user_id=%s serial=%s",
                  self._device.name, self._device.user_id, self._serial)

    # --- Type7 Auth (Delta2, Delta2Max) -------------------------------------

    async def _auth_type7_step1(self, client: BleakClient):
        """Type7 Schritt 1: Public Key senden (SECP160r1, 20 Byte)"""
        self._auth_state = "type7_pubkey_sent"
        self._auth_buffer.clear()
        pubkey = self._crypto.public_key_bytes

        log.debug("[%s] Type7 Auth Schritt 1/4: sende Public Key (%d bytes)",
                  self._device.name, len(pubkey))
        _copy_log(logging.DEBUG,
                  "[%s] Type7 pubkey hex=%s",
                  self._device.name, pubkey.hex())

        # Unverschlüsseltes 5A5A-Frame mit Prefix 0x01 0x00 + SECP160r1-Public-Key
        await self._write(client, encode_simple(b"\x01\x00" + pubkey))

    async def _auth_type7_step2_keyinfo(self, client: BleakClient):
        """Type7 Schritt 2: Key Info Request → erhält neuen Session Key"""
        self._auth_state = "type7_keyinfo_sent"
        log.debug("[%s] Type7 Auth Schritt 2/4: sende Key Info Request", self._device.name)
        await self._write(client, encode_simple(b"\x02"))

    async def _auth_type7_step3_authstatus(self, client: BleakClient):
        """Type7 Schritt 3: Auth Status Request"""
        self._auth_state = "type7_authstatus_sent"
        # cmdSet=0x35, cmdId=0x89 – identisch mit ha-ef-ble getAuthStatus()
        packet = Packet(0x21, 0x35, 0x35, 0x89, b"", 0x01, 0x01, 0x13)
        encoded = self._crypto.encode_packet(packet)

        log.debug("[%s] Type7 Auth Schritt 3/4: sende Auth Status Request", self._device.name)
        _copy_log(logging.DEBUG,
                  "[%s] Type7 Auth-Status-Request: plain=%s encoded=%s",
                  self._device.name, packet.toBytes().hex(), encoded.hex())

        await self._write(client, encoded)

    async def _auth_type7_step4_md5(self, client: BleakClient):
        """Type7 Schritt 4: MD5-Auth (user_id + serial → MD5-Hex)"""
        self._auth_state = "type7_auth_sent"
        md5_payload = build_auth_md5(str(self._device.user_id), self._serial)
        # cmdSet=0x35, cmdId=0x86 – identisch mit ha-ef-ble autoAuthentication()
        packet = Packet(0x21, 0x35, 0x35, 0x86, md5_payload, 0x01, 0x01, 0x13)
        encoded = self._crypto.encode_packet(packet)

        log.debug("[%s] Type7 Auth Schritt 4/4: sende MD5-Auth (payload_len=%d)",
                  self._device.name, len(md5_payload))
        _copy_log(logging.DEBUG,
                  "[%s] Type7 MD5-Auth: user_id=%s serial=%s payload=%s encoded=%s",
                  self._device.name,
                  self._device.user_id, self._serial,
                  md5_payload.decode("ascii"), encoded.hex())

        await self._write(client, encoded)

    # =========================================================================
    # Notify Handler
    # =========================================================================

    def _on_service_changed(self, _characteristic, data: bytes):
        """
        Handler für Service Changed Indications (UUID 00002a05).
        Das Gerät sendet diese nach dem Auth. bleak bestätigt die Indication
        automatisch (ATT Confirmation) sobald start_notify() registriert ist.
        Ohne Bestätigung würde das Gerät nach ~8s disconnecten.
        """
        log.debug("[%s] Service Changed Indication empfangen: %s",
                  self._device.name, data.hex() if data else "(leer)")

    def _on_notify(self, _characteristic, data: bytes):
        log.debug("[%s] BLE Notify empfangen: %d bytes, auth_state=%s",
                  self._device.name, len(data), self._auth_state)
        try:
            self._notify_queue.put_nowait(bytes(data))
        except asyncio.QueueFull:
            log.warning("[%s] Notify-Queue voll, Paket verworfen (Queue-Size=%d)",
                        self._device.name, self._notify_queue.maxsize)

    async def _process_notify_queue(self):
        while self._running:
            try:
                data = await self._notify_queue.get()
                if data is None:
                    return
                await self._handle_notify(data)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("[%s] Notify-Worker-Fehler: %s", self._device.name, e)

    async def _stop_notify_task(self):
        if self._notify_task:
            self._notify_task.cancel()
            try:
                await self._notify_task
            except asyncio.CancelledError:
                pass
            self._notify_task = None

    async def _handle_notify(self, data: bytes):
        try:
            if self._encrypt_type == 1:
                await self._handle_type1(data)
            else:
                await self._handle_type7(data)
        except Exception as e:
            log.warning("[%s] Notify-Verarbeitungsfehler: %s", self._device.name, e)

    # --- Type1 Notify ---------------------------------------------------------

    async def _handle_type1(self, data: bytes):
        """Type1 (PowerStream) Notify Handler"""
        log.debug("[%s] Type1 Notify: %d bytes, auth_state=%s",
                  self._device.name, len(data), self._auth_state)
        _copy_log(logging.DEBUG,
                  "[%s] Type1 raw notify hex=%s", self._device.name, data.hex())

        if self._auth_state == "type1_auth_sent":
            # Auth-Response: versuche Entschlüsselung und prüfe auf cmd_id=0x86
            try:
                packets, _ = self._crypto.decode_packets(data, bytearray())
                for pkt in packets:
                    _copy_log(logging.DEBUG,
                              "[%s] Type1 Auth-Response-Paket: src=0x%02X cmdSet=0x%02X cmdId=0x%02X",
                              self._device.name, pkt.src, pkt.cmdSet, pkt.cmdId)
                    if pkt.cmdSet == 0x35 and pkt.cmdId == 0x86:
                        log.info("[%s] ✓ Type1 Authentifizierung erfolgreich (cmd 0x86)",
                                 self._device.name)
                        await self._mark_authenticated()
                        return
            except Exception as e:
                _copy_log(logging.DEBUG,
                          "[%s] Type1 Auth decode Versuch fehlgeschlagen: %s",
                          self._device.name, e)

            # Fallback: beliebiges Paket ≥ 4 Bytes → als Auth-OK werten
            if data and len(data) > 4:
                log.info("[%s] ✓ Type1 Auth-Response empfangen (Fallback), setze authenticated",
                         self._device.name)
                _copy_log(logging.INFO,
                          "[%s] Type1 Auth Fallback ausgelöst: data_len=%d hex=%s",
                          self._device.name, len(data), data.hex())
                await self._mark_authenticated()
            return

        if self._auth_state == "authenticated":
            packets, self._rx_buffer = self._crypto.decode_packets(
                data, self._rx_buffer
            )
            for pkt in packets:
                _copy_log(logging.DEBUG,
                          "[%s] Type1 Daten-Paket: src=0x%02X cmdSet=0x%02X cmdId=0x%02X payload_len=%d",
                          self._device.name, pkt.src, pkt.cmdSet, pkt.cmdId, len(pkt.payload))
                parsed = self._device.parse_data(pkt)
                if parsed:
                    self._device.update_state(parsed)

    # --- Type7 Notify ---------------------------------------------------------

    async def _handle_type7(self, data: bytes):
        """Type7 (Delta2Max etc.) Notify Handler – folgt ha-ef-ble Schritt für Schritt"""

        if self._auth_state == "type7_pubkey_sent":
            # Gerät sendet seinen Public Key als 5A5A-Frame zurück
            self._auth_buffer.extend(data)
            payload = parse_simple(bytes(self._auth_buffer))
            if payload and len(payload) >= 43:
                self._auth_buffer.clear()
                # Byte 0: type, Byte 1: ?, Byte 2: curve_type,
                # Byte 3..42: 40 Byte SECP160r1 Public Key
                dev_pubkey = payload[3:43]

                _copy_log(logging.DEBUG,
                          "[%s] Type7 Device-Public-Key empfangen: len=%d hex=%s",
                          self._device.name, len(dev_pubkey), dev_pubkey.hex())

                self._crypto.compute_shared_key(dev_pubkey)
                log.debug("[%s] Type7 ECDH: Shared Key berechnet, IV und Session Key gesetzt",
                          self._device.name)
                await self._auth_type7_step2_keyinfo(self._client)
            elif payload is not None:
                _copy_log(logging.WARNING,
                          "[%s] Type7 Public-Key-Response zu kurz: len=%d hex=%s",
                          self._device.name, len(payload) if payload else 0,
                          payload.hex() if payload else "None")
            return

        if self._auth_state == "type7_keyinfo_sent":
            # Gerät sendet verschlüsselte Key Info: [0x02] + sRand(16) + seed(2)
            self._auth_buffer.extend(data)
            payload = parse_simple(bytes(self._auth_buffer))
            if payload and len(payload) > 1 and payload[0] == 0x02:
                self._auth_buffer.clear()

                _copy_log(logging.DEBUG,
                          "[%s] Type7 Key-Info-Response: len=%d hex=%s",
                          self._device.name, len(payload), payload.hex())

                # payload[1:] = verschlüsselt: sRand(16) + seed(2) + Padding
                self._crypto.process_key_info(payload[1:])
                log.debug("[%s] Type7: neuer Session Key aus Key-Info abgeleitet",
                          self._device.name)
                await self._auth_type7_step3_authstatus(self._client)
            elif payload is not None:
                _copy_log(logging.WARNING,
                          "[%s] Type7 Key-Info unerwarteter Typ: payload[0]=0x%02X hex=%s",
                          self._device.name, payload[0] if payload else 0,
                          payload.hex() if payload else "None")
            return

        if self._auth_state == "type7_authstatus_sent":
            # Auth Status Response: erwartet 5A5A-Frame mit f0 xx
            self._auth_buffer.extend(data)
            payload = parse_simple(bytes(self._auth_buffer))
            if payload:
                self._auth_buffer.clear()
                _copy_log(logging.DEBUG,
                          "[%s] Type7 Auth-Status-Response: payload=%s",
                          self._device.name, payload.hex())

                # Beobachtetes Delta2(Max)-Verhalten: `f0 xx` (xx = Status-Byte).
                # Auch `f0 01` ist OK – Gerät ist schon authenticated oder OTA.
                # Solange der erste Byte 0xF0 ist, fahren wir fort.
                if payload[0] == 0xF0:
                    status = _extract_type7_status(payload)
                    log.debug("[%s] Type7 Auth-Status: 0x%02X → MD5-Auth senden",
                              self._device.name, status)
                    await self._auth_type7_step4_md5(self._client)
                else:
                    _copy_log(logging.WARNING,
                              "[%s] Type7 Auth-Status unerwartetes Payload: payload=%s (erwartet f0 xx)",
                              self._device.name, payload.hex())
                    # Trotzdem versuchen fortzufahren
                    await self._auth_type7_step4_md5(self._client)
            elif data:
                _copy_log(logging.WARNING,
                          "[%s] Type7 Auth-Status-Notify nicht dekodierbar: len=%d hex=%s",
                          self._device.name, len(data), data.hex())
            return

        if self._auth_state == "type7_auth_sent":
            # MD5 Auth Response: 5A5A-Frame mit f0 00 (OK) oder f0 xx (Fehler)
            self._auth_buffer.extend(data)
            payload = parse_simple(bytes(self._auth_buffer))
            if payload:
                self._auth_buffer.clear()
                status = _extract_type7_status(payload)
                _copy_log(logging.DEBUG,
                          "[%s] Type7 MD5-Auth-Response: payload=%s status=0x%02X",
                          self._device.name, payload.hex(), status)

                if payload[0] in (0xF0, 0xF1) and status in (0x00, 0x01):
                    log.info("[%s] ✓ Type7 Authentifizierung erfolgreich (status=0x%02X)",
                             self._device.name, status)
                    await self._mark_authenticated()
                else:
                    log.error("[%s] ✗ Type7 MD5-Auth abgelehnt (status=0x%02X payload=%s) – "
                              "user_id oder serial falsch?",
                              self._device.name, status, payload.hex())
                    _copy_log(logging.ERROR,
                              "[%s] Type7 Auth fehlgeschlagen: status=0x%02X serial=%s user_id=%s",
                              self._device.name, status, self._serial, self._device.user_id)
            elif data:
                _copy_log(logging.WARNING,
                          "[%s] Type7 MD5-Auth-Notify nicht dekodierbar: len=%d hex=%s",
                          self._device.name, len(data), data.hex())
            return

        if self._auth_state == "authenticated":
            # Normaler Datenbetrieb: entschlüsselte Packets parsen
            # [COPY] Raw-Hex VOR dem Decode – damit wir sehen was ankommt,
            # auch wenn der Decoder es verwirft (CRC-Fehler, zu kurz, etc.)
            _copy_log(logging.DEBUG,
                      "[%s] Type7 raw notify (authenticated): len=%d hex=%s",
                      self._device.name, len(data), data.hex())

            prev_buf_len = len(self._rx_buffer)
            packets, self._rx_buffer = self._crypto.decode_packets_buffered(
                data, self._rx_buffer
            )

            # [COPY] Wenn keine Packets dekodiert → Diagnose-Info ausgeben
            if not packets:
                _copy_log(logging.DEBUG,
                          "[%s] Type7 decode lieferte 0 Pakete: "
                          "data_len=%d prev_buf=%d new_buf=%d hex=%s",
                          self._device.name,
                          len(data), prev_buf_len, len(self._rx_buffer),
                          data.hex())

            for pkt in packets:
                _copy_log(logging.DEBUG,
                          "[%s] Daten-Paket: src=0x%02X dst=0x%02X cmdSet=0x%02X cmdId=0x%02X "
                          "payload_len=%d payload=%s",
                          self._device.name,
                          pkt.src, pkt.dst, pkt.cmdSet, pkt.cmdId,
                          len(pkt.payload), pkt.payload.hex())

                parsed = self._device.parse_data(pkt)
                if parsed:
                    self._device.update_state(parsed)
                else:
                    log.debug("[%s] Unbekanntes Paket: src=0x%02X cmdSet=0x%02X cmdId=0x%02X",
                              self._device.name, pkt.src, pkt.cmdSet, pkt.cmdId)

    # =========================================================================
    # Hilfsmethoden
    # =========================================================================

    def _on_disconnect(self, _client):
        log.warning("[%s] BLE Verbindung getrennt (auth_state=%s)",
                    self._device.name, self._auth_state)
        if self._auth_state not in ("idle", "authenticated"):
            _copy_log(logging.WARNING,
                      "[%s] Disconnect während Auth: state=%s serial=%s",
                      self._device.name, self._auth_state, self._serial)

        self._authenticated              = False
        self._auth_state                 = "idle"
        self._initial_requests_sent      = False
        self._initial_request_index      = 0
        self._next_initial_at            = 0.0
        self._next_keepalive_at          = 0.0
        self._auth_buffer.clear()
        self._rx_buffer.clear()
        self._client = None

    async def _write(self, client: BleakClient, data: bytes) -> bool:
        """
        Schreibt Daten ans Gerät.

        WICHTIG: response=False für alle Writes, identisch mit ha-ef-ble
        connection.py _sendRequest() wo kein response-Parameter angegeben wird
        (bleak Default = False).

        Mit response=True würde bleak auf eine ATT Write Response warten.
        Das Gerät sendet in dieser Zeit seine Heartbeat-Notifications — diese
        könnten verloren gehen oder das Gerät in einen Fehlerzustand bringen.
        """
        try:
            # MTU nach _acquire_mtu() ist 500 bytes — kein Chunking nötig.
            # Chunk-Grenze als Sicherheitsnetz falls MTU-Negotiation fehlschlägt.
            mtu = getattr(client, "mtu_size", 500) - 3  # -3 für ATT-Header
            if mtu < 20:
                mtu = 200  # Fallback
            for i in range(0, len(data), mtu):
                chunk = data[i:i+mtu]
                # response=False: fire-and-forget, wie ha-ef-ble
                await client.write_gatt_char(UUID_WRITE, chunk, response=False)
                if i + mtu < len(data):
                    await asyncio.sleep(0.02)
            return True
        except Exception as e:
            log.error("[%s] BLE Write-Fehler: %s", self._device.name, e)
            _copy_log(logging.ERROR,
                      "[%s] Write fehlgeschlagen: data_len=%d error=%s",
                      self._device.name, len(data), e)
            return False

    async def _resolve_address(self) -> tuple[Optional[str], Any]:
        """Gibt (BLE-Adresse, adv_data) zurück. Scannt wenn nötig."""
        if self._device.address:
            result = await self._scan_single(self._device.address)
            if result:
                addr, adv = result
                mfr = adv.manufacturer_data
                self._encrypt_type = _get_encrypt_type(mfr)
                self._serial       = _get_serial(mfr)
                log.info("[%s] Gerät gefunden: addr=%s serial=%s encrypt_type=%d",
                         self._device.name, addr, self._serial, self._encrypt_type)
                return addr, adv
            log.warning("[%s] Gerät mit Adresse %s nicht gefunden im Scan, "
                        "versuche direkte Verbindung",
                        self._device.name, self._device.address)
            return self._device.address, None

        log.info("[%s] Scanne nach EcoFlow Geräten (timeout=%ds)...",
                 self._device.name, self._scan_timeout)
        found = await self._scan_all(timeout=self._scan_timeout)
        for addr, (name, adv) in found.items():
            mfr = adv.manufacturer_data
            serial = _get_serial(mfr)
            identity = serial or name
            if self._device.__class__.matches_serial(identity):
                self._device.address = addr
                self._encrypt_type   = _get_encrypt_type(mfr)
                self._serial         = serial
                log.info("[%s] Gerät gefunden per Scan: name=%s addr=%s serial=%s encrypt_type=%d",
                         self._device.name, name, addr, serial, self._encrypt_type)
                return addr, adv
        return None, None

    async def _scan_single(self, address: str, timeout: int = 10):
        """Scannt gezielt nach einer MAC-Adresse."""
        result = None

        def on_detect(device, adv):
            nonlocal result
            if device.address.upper() == address.upper():
                result = (device.address, adv)

        scanner = BleakScanner(detection_callback=on_detect)
        await scanner.start()
        for _ in range(timeout * 10):
            if result:
                break
            await asyncio.sleep(0.1)
        await scanner.stop()
        return result

    async def _scan_all(self, timeout: int = 30) -> dict:
        """Scannt nach allen EcoFlow Geräten."""
        found = {}

        def on_detect(device, adv):
            if EF_MANUFACTURER_ID in adv.manufacturer_data:
                found[device.address] = (device.name or device.address, adv)
                log.info("[SCAN] Gefunden: %s (%s)", device.name, device.address)

        scanner = BleakScanner(detection_callback=on_detect)
        await scanner.start()
        await asyncio.sleep(timeout)
        await scanner.stop()
        return found
