import asyncio
import unittest

from ble_manager import BLEDeviceManager
from protocol import Packet
from devices.base import EcoFlowDevice


class DummyDevice(EcoFlowDevice):
    DEVICE_TYPE = "dummy"
    SERIAL_PREFIX = ["DUMMY"]

    def parse_data(self, decrypted_payload):
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

    async def test_mark_authenticated_resets_poll_state_without_missing_helpers(self):
        self.manager._poll_index = 7
        self.manager._next_poll_at = 99.0

        await self.manager._mark_authenticated()

        self.assertTrue(self.manager._authenticated)
        self.assertEqual(self.manager._auth_state, "authenticated")
        self.assertEqual(self.manager._poll_index, 0)
        self.assertEqual(self.manager._next_poll_at, 0.0)

    async def test_poll_initial_request_uses_initialized_poll_attributes(self):
        client = FakeClient()

        await self.manager._poll_initial_request(client)

        self.assertEqual(len(client.writes), 1)
        self.assertEqual(self.manager._poll_index, 0)
        self.assertGreater(self.manager._next_poll_at, 0.0)

    async def test_poll_initial_request_retries_same_packet_after_write_failure(self):
        client = FakeClient(fail=True)

        await self.manager._poll_initial_request(client)

        self.assertEqual(self.manager._poll_index, 0)
        self.assertGreaterEqual(self.manager._next_poll_at, 1.0)

    async def test_disconnect_clears_poll_state(self):
        self.manager._authenticated = True
        self.manager._auth_state = "authenticated"
        self.manager._poll_index = 3
        self.manager._next_poll_at = 12.0
        self.manager._auth_buffer.extend(b"abc")
        self.manager._rx_buffer.extend(b"def")
        self.manager._client = object()

        self.manager._on_disconnect(None)

        self.assertFalse(self.manager._authenticated)
        self.assertEqual(self.manager._auth_state, "idle")
        self.assertEqual(self.manager._poll_index, 0)
        self.assertEqual(self.manager._next_poll_at, 0.0)
        self.assertEqual(self.manager._auth_buffer, bytearray())
        self.assertEqual(self.manager._rx_buffer, bytearray())
        self.assertIsNone(self.manager._client)


if __name__ == "__main__":
    unittest.main()
