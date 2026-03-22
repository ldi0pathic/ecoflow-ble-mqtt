# =============================================================================
# ble_manager.py - BLE Verbindung + Auth Handshake (portiert von ha-ef-ble)
# Unterstützt encrypt_type 1 (PowerStream) und 7 (Delta2, Delta2Max etc.)
# =============================================================================

import asyncio
import logging
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

                log.info("[%s] Verbinde mit %s (encrypt_type=%d)...",
                         self._device.name, ble_address, self._encrypt_type)

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

                        if self._encrypt_type == 1:
                            self._crypto = Type1Crypto(self._serial)
                        else:
                            self._crypto = Type7Crypto()

                        log.info("[%s] Verbunden!", self._device.name)
                        self._notify_queue = asyncio.Queue(maxsize=self._notify_queue.maxsize)
                        self._notify_task = asyncio.create_task(self._process_notify_queue())
                        await client.start_notify(UUID_NOTIFY, self._on_notify)
                        await self._start_auth(client)

                        while self._running and client.is_connected:
                            try:
                                packet = self._send_queue.get_nowait()
                                encoded = self._crypto.encode_packet(packet)
                                await self._write(client, encoded)
                            except asyncio.QueueEmpty:
                                pass
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
        log.debug("[%s] Type1: Auth gesendet", self._device.name)

    # --- Type7 Auth (Delta2, Delta2Max) -------------------------------------

    async def _auth_type7_step1(self, client: BleakClient):
        """Type7 Schritt 1: Public Key senden"""
        self._auth_state = "type7_pubkey_sent"
        self._auth_buffer.clear()
        pubkey = self._crypto.public_key_bytes
        log.debug("[%s] Type7: sende Public Key (%d bytes)",
                  self._device.name, len(pubkey))
        # Upstream-Protokoll erwartet ein unverschlüsseltes 5A5A-Command-Frame
        # mit Prefix 0x01 0x00 vor dem eigentlichen SECP160r1-Public-Key.
        await self._write(client, encode_simple(b"\x01\x00" + pubkey))

    async def _auth_type7_step2_keyinfo(self, client: BleakClient):
        """Type7 Schritt 2: Key Info Request"""
        self._auth_state = "type7_keyinfo_sent"
        to_send = encode_simple(b"\x02")
        log.debug("[%s] Type7: sende Key Info Request", self._device.name)
        await self._write(client, to_send)

    async def _auth_type7_step3_authstatus(self, client: BleakClient):
        """Type7 Schritt 3: Auth Status Request"""
        self._auth_state = "type7_authstatus_sent"
        packet = Packet(0x21, 0x35, 0x35, 0x89, b"", 0x01, 0x01, 0x03)
        encoded = self._crypto.encode_packet(packet)
        log.debug("[%s] Type7: sende Auth Status Request", self._device.name)
        _copy_log(logging.DEBUG,
                  "[%s] Type7 Auth Status Request: plain=%s encoded=%s",
                  self._device.name, packet.toBytes().hex(), encoded.hex())
        await self._write(client, encoded)

    async def _auth_type7_step4_md5(self, client: BleakClient):
        """Type7 Schritt 4: MD5-Auth"""
        self._auth_state = "type7_auth_sent"
        md5_payload = build_auth_md5(str(self._device.user_id), self._serial)
        packet = Packet(0x21, 0x35, 0x35, 0x86, md5_payload, 0x01, 0x01, 0x03)
        encoded = self._crypto.encode_packet(packet)
        log.debug("[%s] Type7: sende MD5-Auth Packet", self._device.name)
        _copy_log(logging.DEBUG,
                  "[%s] Type7 MD5-Auth Request: payload_len=%d encoded=%s",
                  self._device.name, len(md5_payload), encoded.hex())
        await self._write(client, encoded)

    # =========================================================================
    # Notify Handler
    # =========================================================================

    def _on_notify(self, _characteristic, data: bytes):
        log.debug("[%s] Notify: %d bytes, auth_state=%s",
                  self._device.name, len(data), self._auth_state)
        try:
            self._notify_queue.put_nowait(bytes(data))
        except asyncio.QueueFull:
            log.warning("[%s] Notify-Queue voll, Paket verworfen", self._device.name)

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
            log.warning("[%s] Notify-Fehler: %s", self._device.name, e)

    async def _handle_type1(self, data: bytes):
        """Type1 (PowerStream) Notify Handler"""
        log.debug("[%s] Type1 Notify: %s", self._device.name, data.hex())

        if self._auth_state == "type1_auth_sent":
            # Auth-Response — der PowerStream schickt ein verschlüsseltes Packet zurück
            # Versuche es zu entschlüsseln und auf cmd_id=0x86 zu prüfen
            try:
                packets, _ = self._crypto.decode_packets(data, bytearray())
                for pkt in packets:
                    log.debug("[%s] Auth Response Packet: src=0x%02X cmdSet=0x%02X cmdId=0x%02X",
                              self._device.name, pkt.src, pkt.cmdSet, pkt.cmdId)
                    if pkt.cmdSet == 0x35 and pkt.cmdId == 0x86:
                        log.info("[%s] ✓ Authentifizierung erfolgreich!", self._device.name)
                        self._authenticated = True
                        self._auth_state = "authenticated"
                        return
            except Exception as e:
                log.debug("[%s] Auth decode attempt: %s", self._device.name, e)

            # Fallback: wenn überhaupt ein Packet kommt → als erfolgreich werten
            if data and len(data) > 4:
                log.info("[%s] ✓ Auth Response empfangen, setze authenticated",
                         self._device.name)
                self._authenticated = True
                self._auth_state = "authenticated"

        if self._auth_state == "authenticated":
            packets, self._rx_buffer = self._crypto.decode_packets(
                data, self._rx_buffer
            )
            for pkt in packets:
                log.debug("[%s] Packet: src=0x%02X cmdSet=0x%02X cmdId=0x%02X payload=%s",
                          self._device.name, pkt.src, pkt.cmdSet, pkt.cmdId,
                          pkt.payload.hex())
                parsed = self._device.parse_data(pkt)
                if parsed:
                    self._device.update_state(parsed)

    async def _handle_type7(self, data: bytes):
        """Type7 (Delta2 etc.) Notify Handler"""
        if self._auth_state == "type7_pubkey_sent":
            # Device Public Key wird als simples 5A5A-Command-Frame zurückgegeben.
            self._auth_buffer.extend(data)
            payload = parse_simple(bytes(self._auth_buffer))
            if payload and len(payload) >= 43:
                self._auth_buffer.clear()
                dev_pubkey = payload[3:43]
                self._crypto.compute_shared_key(dev_pubkey)
                log.debug("[%s] Type7: Device Public Key empfangen", self._device.name)
                await self._auth_type7_step2_keyinfo(self._client)
            return

        if self._auth_state == "type7_keyinfo_sent":
            # Key Info Response
            self._auth_buffer.extend(data)
            payload = parse_simple(bytes(self._auth_buffer))
            if payload and len(payload) > 1 and payload[0] == 0x02:
                self._auth_buffer.clear()
                self._crypto.process_key_info(payload[1:])
                log.debug("[%s] Type7: Session Key empfangen", self._device.name)
                await self._auth_type7_step3_authstatus(self._client)
            return

        if self._auth_state == "type7_authstatus_sent":
            # Auth Status Response
            packets = self._crypto.decode_packets(data)
            if packets:
                payload = packets[0].payload
                status = payload[0] if payload else 0x00
                log.debug("[%s] Type7: Auth Status empfangen (payload=%s, status=0x%02X)",
                          self._device.name, payload.hex(), status)
                _copy_log(logging.DEBUG,
                          "[%s] Type7 Auth Status Response: payload=%s status=0x%02X",
                          self._device.name, payload.hex(), status)
                await self._auth_type7_step4_md5(self._client)
            return

        if self._auth_state == "type7_auth_sent":
            # MD5 Auth Response
            packets = self._crypto.decode_packets(data)
            for pkt in packets:
                payload = pkt.payload
                status = payload[0] if payload else 0x00
                if status == 0x00:
                    log.info("[%s] ✓ Authentifizierung erfolgreich!", self._device.name)
                    self._authenticated = True
                    self._auth_state = "authenticated"
                    _copy_log(logging.INFO,
                              "[%s] Type7 MD5-Auth accepted: payload=%s",
                              self._device.name, payload.hex())
                else:
                    log.warning("[%s] Type7: MD5-Auth abgelehnt (status=0x%02X)",
                                self._device.name, status)
                    _copy_log(logging.WARNING,
                              "[%s] Type7 MD5-Auth rejected: payload=%s status=0x%02X serial=%s",
                              self._device.name, payload.hex(), status, self._serial)
                return

        if self._auth_state == "authenticated":
            packets = self._crypto.decode_packets(data)
            for pkt in packets:
                parsed = self._device.parse_data(pkt)
                if parsed:
                    self._device.update_state(parsed)

    # =========================================================================
    # Hilfsmethoden
    # =========================================================================

    def _on_disconnect(self, _client):
        log.warning("[%s] BLE Verbindung getrennt", self._device.name)
        if self._auth_state != "authenticated":
            _copy_log(logging.WARNING,
                      "[%s] Disconnect during auth: state=%s serial=%s",
                      self._device.name, self._auth_state, self._serial)
        self._authenticated = False
        self._auth_state    = "idle"
        self._auth_buffer.clear()
        self._rx_buffer.clear()
        self._client = None

    async def _write(self, client: BleakClient, data: bytes):
        """Schreibt Daten ans Gerät, aufgeteilt in MTU-Chunks."""
        try:
            mtu = 200
            with_response = self._encrypt_type != 1
            for i in range(0, len(data), mtu):
                chunk = data[i:i+mtu]
                await client.write_gatt_char(UUID_WRITE, chunk,
                                             response=with_response)
                if len(data) > mtu:
                    await asyncio.sleep(0.02)
        except Exception as e:
            log.error("[%s] Write-Fehler: %s", self._device.name, e)

    async def _resolve_address(self) -> tuple[Optional[str], Any]:
        """Gibt (BLE-Adresse, adv_data) zurück. Scannt wenn nötig."""
        if self._device.address:
            # Kurzer Scan um Manufacturer Data zu holen
            result = await self._scan_single(self._device.address)
            if result:
                addr, adv = result
                mfr = adv.manufacturer_data
                self._encrypt_type = _get_encrypt_type(mfr)
                self._serial       = _get_serial(mfr)
                log.info("[%s] Seriennummer: %s, encrypt_type: %d",
                         self._device.name, self._serial, self._encrypt_type)
                return addr, adv
            return self._device.address, None

        # Vollständiger Scan
        log.info("[%s] Scanne nach EcoFlow Geräten...", self._device.name)
        found = await self._scan_all(timeout=self._scan_timeout)
        for addr, (name, adv) in found.items():
            mfr = adv.manufacturer_data
            serial = _get_serial(mfr)
            identity = serial or name
            if self._device.__class__.matches_serial(identity):
                self._device.address = addr
                self._encrypt_type   = _get_encrypt_type(mfr)
                self._serial         = serial
                log.info("[%s] Gefunden: %s / %s (%s), encrypt_type=%d",
                         self._device.name, identity, name, addr, self._encrypt_type)
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
            if not device.name:
                return
            name = device.name.upper()
            if EF_MANUFACTURER_ID in adv.manufacturer_data:
                found[device.address] = (device.name, adv)
                log.info("  Gefunden: %s (%s)", device.name, device.address)

        scanner = BleakScanner(detection_callback=on_detect)
        await scanner.start()
        await asyncio.sleep(timeout)
        await scanner.stop()
        return found
