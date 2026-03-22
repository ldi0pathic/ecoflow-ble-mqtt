import unittest

from devices.delta2max import Delta2Max
from protocol import Type7Crypto, encode_simple


class Delta2MaxTests(unittest.TestCase):
    def setUp(self):
        self.device = Delta2Max("delta2_max", "AA:BB:CC:DD:EE:FF", 123456)

    def test_initial_requests_use_expected_request_order_and_payload(self):
        requests = self.device.get_initial_requests()

        self.assertEqual(len(requests), 5)
        self.assertEqual(
            [(packet.dst, packet.cmdSet, packet.cmdId) for packet in requests],
            [
                (0x02, 0x20, 0x02),
                (0x03, 0x20, 0x02),
                (0x03, 0x20, 0x32),
                (0x04, 0x20, 0x02),
                (0x05, 0x20, 0x02),
            ],
        )
        self.assertTrue(all(packet.payload == b"\x00" for packet in requests))
        self.assertTrue(all(packet.version == 0x02 for packet in requests))

    def test_build_set_command_clamps_charge_limits(self):
        max_packet = self.device.build_set_command("battery_charge_limit_max", 150)
        min_packet = self.device.build_set_command("battery_charge_limit_min", -5)

        self.assertIsNotNone(max_packet)
        self.assertEqual(max_packet.payload, bytes([100]))
        self.assertIsNotNone(min_packet)
        self.assertEqual(min_packet.payload, bytes([0]))

    def test_build_set_command_rejects_invalid_values(self):
        self.assertIsNone(self.device.build_set_command("battery_charge_limit_max", "bad"))
        self.assertIsNone(self.device.build_set_command("unknown", 1))


class Type7CryptoFrameTests(unittest.TestCase):
    def test_decode_packets_buffered_ignores_simple_frames_after_auth(self):
        crypto = Type7Crypto()

        packets, buffer = crypto.decode_packets_buffered(encode_simple(b"\xf0\x01"), bytearray())

        self.assertEqual(packets, [])
        self.assertEqual(buffer, bytearray())


if __name__ == "__main__":
    unittest.main()
