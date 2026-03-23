import asyncio
import unittest

from ble_manager import BLEDeviceManager
from protocol import Packet
from devices.base import EcoFlowDevice


class DummyDevice(EcoFlowDevice):
    DEVICE_TYPE = "dummy"
    SERIAL_PREFIX = ["DUMMY"]

    def parse_data(self, packet):
        return {}

    def build_set_command(self, key, value):
        return None

    def get_initial_requests(self):
        return [Packet(0x21, 0x02, 0x20, 0x02, b"", version=0x02)]


class FakeCrypto:
    def encode_packet(self, packet):
        return b"encoded:" + bytes([packet.dst, packet.cmdSet, packet.cmdId])


class FakeClient:
    def __init__(self, fail=False):
        self.fail = fail
        self.writes = []

    async def write_gatt_char(self, uuid, chunk, response=False):
        if self.fail:
            raise RuntimeError("write failed")
        self.writes.append((uuid, chunk, response))


class BLEManagerAuthStateTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.device = DummyDevice("dummy", "AA:BB:CC:DD:EE:FF", 123456)
        self.manager = BLEDeviceManager(self.device)
        self.manager._crypto = FakeCrypto()

    async def test_mark_authenticated_resets_initial_request_state(self):
        """Nach _mark_authenticated() müssen Initial-Request-State-Vars zurückgesetzt sein."""
        # Simuliere Zustand nach einem früheren Verbindungsversuch
        self.manager._initial_requests_sent = True
        self.manager._initial_request_index = 7
        self.manager._next_initial_at       = 99.0

        await self.manager._mark_authenticated()

        self.assertTrue(self.manager._authenticated)
        self.assertEqual(self.manager._auth_state, "authenticated")
        # Initial-Request-Phase muss neu starten
        self.assertFalse(self.manager._initial_requests_sent)
        self.assertEqual(self.manager._initial_request_index, 0)
        self.assertEqual(self.manager._next_initial_at, 0.0)

    async def test_send_next_initial_request_advances_index(self):
        """Nach erfolgreichem Write: Index um 1 erhöht, next_initial_at gesetzt."""
        client = FakeClient()
        await self.manager._mark_authenticated()

        await self.manager._send_next_initial_request(client)

        self.assertEqual(len(client.writes), 1)
        # Index wurde auf 1 gesetzt (alle Requests = 1, also jetzt "done")
        self.assertEqual(self.manager._initial_request_index, 1)
        self.assertGreater(self.manager._next_initial_at, 0.0)

    async def test_send_next_initial_request_marks_done_when_all_sent(self):
        """Sobald alle Requests gesendet, wird _initial_requests_sent=True gesetzt."""
        client = FakeClient()
        await self.manager._mark_authenticated()

        # Ersten (und einzigen) Request senden
        await self.manager._send_next_initial_request(client)
        self.assertFalse(self.manager._initial_requests_sent)

        # Nächster Aufruf: index >= len(requests) → done
        self.manager._next_initial_at = 0.0  # Zeitsperre umgehen
        await self.manager._send_next_initial_request(client)
        self.assertTrue(self.manager._initial_requests_sent)

    async def test_send_next_initial_request_retries_on_write_failure(self):
        """Bei Write-Fehler: Index bleibt gleich, next_initial_at auf +1s gesetzt."""
        client = FakeClient(fail=True)
        await self.manager._mark_authenticated()

        await self.manager._send_next_initial_request(client)

        # Index darf NICHT erhöht worden sein
        self.assertEqual(self.manager._initial_request_index, 0)
        self.assertGreaterEqual(self.manager._next_initial_at, 1.0)

    async def test_send_next_initial_request_respects_rate_limit(self):
        """Wenn next_initial_at in der Zukunft liegt, wird nichts gesendet."""
        import time
        client = FakeClient()
        await self.manager._mark_authenticated()
        self.manager._next_initial_at = time.monotonic() + 100.0  # weit in der Zukunft

        await self.manager._send_next_initial_request(client)

        # Kein Write, kein Index-Fortschritt
        self.assertEqual(len(client.writes), 0)
        self.assertEqual(self.manager._initial_request_index, 0)

    async def test_disconnect_clears_all_state(self):
        """_on_disconnect() muss alle Zustände vollständig zurücksetzen."""
        self.manager._authenticated          = True
        self.manager._auth_state             = "authenticated"
        self.manager._initial_requests_sent  = True
        self.manager._initial_request_index  = 3
        self.manager._next_initial_at        = 12.0
        self.manager._auth_buffer.extend(b"abc")
        self.manager._rx_buffer.extend(b"def")
        self.manager._client = object()

        self.manager._on_disconnect(None)

        self.assertFalse(self.manager._authenticated)
        self.assertEqual(self.manager._auth_state, "idle")
        self.assertFalse(self.manager._initial_requests_sent)
        self.assertEqual(self.manager._initial_request_index, 0)
        self.assertEqual(self.manager._next_initial_at, 0.0)
        self.assertEqual(self.manager._auth_buffer, bytearray())
        self.assertEqual(self.manager._rx_buffer, bytearray())
        self.assertIsNone(self.manager._client)


if __name__ == "__main__":
    unittest.main()
