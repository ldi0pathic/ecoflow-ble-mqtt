# =============================================================================
# protocol.py - EcoFlow BLE Protokoll (portiert von ha-ef-ble)
# Quelle: https://github.com/rabits/ha-ef-ble (Apache-2.0)
# =============================================================================

import hashlib
import logging
import struct

import ecdsa
from Crypto.Cipher import AES
from Crypto.Hash import SHA256
from Crypto.Protocol.DH import key_agreement
from Crypto.Protocol.KDF import HKDF
from Crypto.PublicKey import ECC
from Crypto.Random import get_random_bytes
from Crypto.Util.Padding import pad, unpad
from crc import Calculator, Configuration, Crc8

log = logging.getLogger(__name__)

# --- BLE UUIDs ---------------------------------------------------------------
UUID_NOTIFY = "00000003-0000-1000-8000-00805f9b34fb"
UUID_WRITE  = "00000002-0000-1000-8000-00805f9b34fb"

# --- CRC (aus crc.py von ha-ef-ble) -----------------------------------------
_crc16_cfg = Configuration(
    width=16, polynomial=0x8005, init_value=0x0000,
    final_xor_value=0x0000, reverse_input=True, reverse_output=True,
)

def crc8(data: bytes) -> int:
    return Calculator(Crc8.CCITT).checksum(data)

def crc16(data: bytes) -> int:
    return Calculator(_crc16_cfg).checksum(data)


# =============================================================================
# Packet (aus packet.py von ha-ef-ble)
# =============================================================================

class Packet:
    PREFIX = b"\xaa"

    def __init__(self, src, dst, cmd_set, cmd_id, payload=b"",
                 dsrc=1, ddst=1, version=3, seq=None, product_id=0):
        self._src        = src
        self._dst        = dst
        self._cmd_set    = cmd_set
        self._cmd_id     = cmd_id
        self._payload    = payload
        self._dsrc       = dsrc
        self._ddst       = ddst
        self._version    = version
        self._seq        = seq if seq is not None else b"\x00\x00\x00\x00"
        self._product_id = product_id

    @property
    def src(self):     return self._src
    @property
    def dst(self):     return self._dst
    @property
    def cmdSet(self):  return self._cmd_set
    @property
    def cmdId(self):   return self._cmd_id
    @property
    def payload(self): return self._payload
    @property
    def version(self): return self._version

    def toBytes(self) -> bytes:
        data  = Packet.PREFIX
        data += struct.pack("<B", self._version) + struct.pack("<H", len(self._payload))
        data += struct.pack("<B", crc8(data))
        data += b"\x0d" + self._seq + b"\x00\x00"
        data += struct.pack("<B", self._src) + struct.pack("<B", self._dst)
        if self._version >= 0x03:
            data += struct.pack("<B", self._dsrc) + struct.pack("<B", self._ddst)
        data += struct.pack("<B", self._cmd_set) + struct.pack("<B", self._cmd_id)
        data += self._payload
        data += struct.pack("<H", crc16(data))
        return data

    @staticmethod
    def fromBytes(data: bytes, xor_payload: bool = False) -> "Packet":
        if not data.startswith(Packet.PREFIX):
            raise ValueError(f"Bad prefix: {data.hex()}")
        version        = data[1]
        payload_length = struct.unpack("<H", data[2:4])[0]
        if crc8(data[:4]) != data[4]:
            raise ValueError(f"CRC8 mismatch: {data.hex()}")
        if version in [2, 3, 4]:
            if crc16(data[:-2]) != struct.unpack("<H", data[-2:])[0]:
                raise ValueError(f"CRC16 mismatch: {data.hex()}")
        seq           = data[6:10]
        src           = data[12]
        dst           = data[13]
        payload_start = 16 if version == 2 else 18
        dsrc = ddst   = 0
        if version == 2:
            cmd_set, cmd_id = data[14:16]
        else:
            dsrc, ddst, cmd_set, cmd_id = data[14:18]
        payload = data[payload_start: payload_start + payload_length] if payload_length else b""

        # XOR payload mit erstem Seq-Byte wenn gesetzt (PowerStream benötigt das)
        if xor_payload and seq[0] != 0:
            payload = bytes([c ^ seq[0] for c in payload])
            
        return Packet(src=src, dst=dst, cmd_set=cmd_set, cmd_id=cmd_id,
                      payload=payload, dsrc=dsrc, ddst=ddst, version=version, seq=seq)


# =============================================================================
# SimplePacketAssembler — unverschlüsselte EncPackets für Auth-Handshake
# =============================================================================

PREFIX_5A = b"\x5a\x5a"

def encode_simple(payload: bytes) -> bytes:
    """Baut ein unverschlüsseltes 5A5A-EncPacket (für Auth-Kommandos)"""
    frame_type   = 0x11
    payload_type = 0x01
    inner        = bytes([frame_type, payload_type]) + struct.pack("<H", len(payload)) + payload
    return PREFIX_5A + inner + struct.pack("<H", crc16(inner))

def parse_simple(data: bytes) -> bytes | None:
    """Parst ein unverschlüsseltes 5A5A-EncPacket, gibt payload zurück"""
    start = data.find(PREFIX_5A)
    if start < 0:
        return None
    data = data[start:]
    if len(data) < 8:
        return None
    inner_len = struct.unpack("<H", data[4:6])[0]
    end       = 6 + inner_len
    if end > len(data):
        return None
    inner    = data[2:end - 2]
    crc_recv = struct.unpack("<H", data[end - 2: end])[0]
    if crc16(inner) != crc_recv:
        return None
    return inner[4:]  # nach frame_type(1)+payload_type(1)+length(2)


# =============================================================================
# Type7 Crypto — ECDH SECP160r1 + AES-CBC (alle Geräte außer PowerStream)
# =============================================================================

class Type7Crypto:
    def __init__(self):
        self._private_key    = ecdsa.SigningKey.generate(curve=ecdsa.SECP160r1)
        self.public_key_bytes = self._private_key.get_verifying_key().to_string()
        self._session_key: bytes | None = None
        self._iv:          bytes | None = None

    def compute_shared_key(self, dev_pubkey_bytes: bytes):
        dev_pub           = ecdsa.VerifyingKey.from_string(dev_pubkey_bytes, curve=ecdsa.SECP160r1)
        shared            = ecdsa.ECDH(ecdsa.SECP160r1, self._private_key, dev_pub).generate_sharedsecret_bytes()
        self._iv          = hashlib.md5(shared).digest()
        self._session_key = shared[:16]
        log.debug("Type7: shared key established, iv=%s", self._iv.hex())

    def process_key_info(self, encrypted_data: bytes):
        """Verarbeitet Key-Info-Response und aktualisiert Session Key"""
        raw       = self.decrypt_raw(encrypted_data)
        s_rand    = raw[:16]
        seed      = raw[16:18]
        new_key   = self._gen_session_key(seed, s_rand)
        self._session_key = new_key
        log.debug("Type7: session key updated")

    def _gen_session_key(self, seed: bytes, s_rand: bytes) -> bytes:
        cipher    = AES.new(self._session_key, AES.MODE_CBC, self._iv)
        decrypted = unpad(cipher.decrypt(
            pad(s_rand + seed + bytes(14), AES.block_size)
        ), AES.block_size)
        return decrypted[:16]

    def encrypt(self, data: bytes) -> bytes:
        cipher = AES.new(self._session_key, AES.MODE_CBC, self._iv)
        return cipher.encrypt(pad(data, AES.block_size))

    def decrypt(self, data: bytes) -> bytes:
        cipher = AES.new(self._session_key, AES.MODE_CBC, self._iv)
        return unpad(cipher.decrypt(data), AES.block_size)

    def decrypt_raw(self, data: bytes) -> bytes:
        cipher = AES.new(self._session_key, AES.MODE_CBC, self._iv)
        return cipher.decrypt(data)

    def encode_packet(self, packet: Packet) -> bytes:
        """Kodiert ein Packet mit EncPacket-Wrapper (5A5A)"""
        raw       = packet.toBytes()
        encrypted = self.encrypt(raw)
        frame_type   = 0x10
        payload_type = 0x01
        inner        = bytes([frame_type, payload_type]) + struct.pack("<H", len(encrypted)) + encrypted
        return PREFIX_5A + inner + struct.pack("<H", crc16(inner))

    def decode_packets(self, data: bytes) -> list[Packet]:
        """Parst und entschlüsselt eingehende EncPackets"""
        packets = []
        while data:
            start = data.find(PREFIX_5A)
            if start < 0:
                break
            if start > 0:
                data = data[start:]
            if len(data) < 8:
                break
            inner_len = struct.unpack("<H", data[4:6])[0]
            end       = 6 + inner_len
            if end > len(data):
                break
            inner    = data[2:end - 2]
            crc_recv = struct.unpack("<H", data[end - 2: end])[0]
            data     = data[end:]
            if crc16(inner) != crc_recv:
                continue
            payload_enc = inner[4:]
            try:
                decrypted = self.decrypt(payload_enc)
                pkt       = Packet.fromBytes(decrypted)
                packets.append(pkt)
            except Exception as e:
                log.debug("Decode error: %s", e)
        return packets

    @property
    def is_ready(self) -> bool:
        return self._session_key is not None


# =============================================================================
# Type1 Crypto — ECIES Curve25519 + AES-CBC null-padded (PowerStream)
# =============================================================================

_EF_PUBKEY_TYPE1 = ECC.import_key(
    "-----BEGIN PUBLIC KEY-----\n"
    "MCowBQYDK2VuAyEAjyDKgWi1v2IO417ZsQC3VIa5U6bs8TzQQGxzlvCKWkM=\n"
    "-----END PUBLIC KEY-----"
)

class Type1Crypto:
    """Type1 Encryption für PowerStream — Key aus Seriennummer"""

    def __init__(self, dev_sn: str):
        key        = hashlib.md5(dev_sn.encode()).digest()
        iv         = hashlib.md5(dev_sn[::-1].encode()).digest()
        self._key  = key
        self._iv   = iv

    def encrypt(self, data: bytes) -> bytes:
        padded_len = (len(data) + 15) // 16 * 16
        padded     = data + b"\x00" * (padded_len - len(data))
        cipher     = AES.new(self._key, AES.MODE_CBC, self._iv)
        return cipher.encrypt(padded)

    def decrypt(self, data: bytes) -> bytes:
        cipher = AES.new(self._key, AES.MODE_CBC, self._iv)
        return cipher.decrypt(data)

    def encode_packet(self, packet: Packet) -> bytes:
        raw        = packet.toBytes()
        header     = raw[:5]
        inner      = raw[5:]
        encrypted  = self.encrypt(inner)
        return header + encrypted

    def decode_packets(self, data: bytes, buffer: bytearray) -> tuple[list[Packet], bytearray]:
        data    = bytes(buffer) + data
        buffer  = bytearray()
        packets = []
        while data:
            start = data.find(Packet.PREFIX)
            if start < 0:
                data = b""
                break
            if start > 0:
                data = data[start:]
            if len(data) < 5:
                buffer = bytearray(data)
                break
            if crc8(data[:4]) != data[4]:
                data = data[1:]
                continue
            payload_length = struct.unpack("<H", data[2:4])[0]
            version        = data[1]
            inner_overhead = 15 if version >= 3 else 13
            inner_len      = inner_overhead + payload_length
            encrypted_len  = (inner_len + 15) // 16 * 16
            frame_len      = 5 + encrypted_len
            if len(data) < frame_len:
                buffer = bytearray(data)
                break
            header         = data[:5]
            encrypted_body = data[5:frame_len]
            data           = data[frame_len:]
            try:
                decrypted = self.decrypt(encrypted_body)
                pkt = Packet.fromBytes(header + decrypted[:inner_len], xor_payload=True)
                packets.append(pkt)
            except Exception as e:
                log.debug("Type1 decode error: %s", e)
        return packets, buffer

    @property
    def is_ready(self) -> bool:
        return True


# =============================================================================
# Auth Helper
# =============================================================================

def build_auth_md5(user_id: str, dev_sn: str) -> bytes:
    """MD5(user_id + serial) als HEX-ASCII — für autoAuthentication"""
    md5_data = hashlib.md5((user_id + dev_sn).encode("ASCII")).digest()
    return ("".join(f"{c:02X}" for c in md5_data)).encode("ASCII")
