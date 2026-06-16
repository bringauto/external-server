import unittest

from fleet_protocol_protobuf_files.InternalProtocol_pb2 import Device  # type: ignore
from fleet_protocol_protobuf_files.ExternalProtocol_pb2 import Status  # type: ignore

from external_server.adapters.mqtt.adapter import MQTTClientAdapter  # type: ignore
from external_server.models.messages import connect_msg, status  # type: ignore
from external_server.models.devices import device_status as _device_status  # type: ignore


class Test_Get_Connect_Message_Discards_Stale_Statuses(unittest.TestCase):
    """Regression for the GW<->ES reconnect deadlock.

    A status left in the received-message queue ahead of the connect (e.g. buffered around a
    reconnect, while the gateway was still streaming at status rate) must NOT abort the connect
    sequence. Before the fix, get_connect_message popped exactly one message and returned None on
    a non-connect, so the sequence failed, cleared context, retried, and met the same buffered
    status forever -> the GUI banner stayed permanently 'STATUS UNAVAILABLE'. It must instead
    discard non-connect messages and return the connect sitting behind them.
    """

    def setUp(self) -> None:
        # broker_host=""/port=0 -> no real broker; we drive the received-message queue directly.
        self.adapter = MQTTClientAdapter("company", "car", timeout=1, broker_host="", port=0)
        self.device = Device(module=1000, deviceType=0, deviceName="Test", deviceRole="test")

    def test_returns_connect_when_a_status_is_queued_ahead_of_it(self) -> None:
        self.adapter.received_messages.put(
            status("id", Status.CONNECTING, 0, _device_status(self.device))
        )
        self.adapter.received_messages.put(connect_msg("id", "company", [self.device]))
        msg = self.adapter.get_connect_message()
        self.assertIsNotNone(msg)  # fails before the fix (returned None on the leading status)
        self.assertEqual(msg.sessionId, "id")

    def test_discards_several_stale_statuses_before_the_connect(self) -> None:
        for counter in range(5):
            self.adapter.received_messages.put(
                status("id", Status.RUNNING, counter, _device_status(self.device))
            )
        self.adapter.received_messages.put(connect_msg("id", "company", [self.device]))
        msg = self.adapter.get_connect_message()
        self.assertIsNotNone(msg)
        self.assertEqual(msg.sessionId, "id")

    def test_returns_none_within_timeout_when_no_connect_arrives(self) -> None:
        # Only statuses, never a connect: must give up (caller retries) and not hang.
        self.adapter.received_messages.put(
            status("id", Status.RUNNING, 0, _device_status(self.device))
        )
        self.assertIsNone(self.adapter.get_connect_message())


if __name__ == "__main__":
    unittest.main()
