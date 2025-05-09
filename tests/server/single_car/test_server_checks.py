import unittest
import sys

sys.path.append(".")

from external_server.models.exceptions import ConnectSequenceFailure
from external_server import CarServer as ES
from fleet_protocol_protobuf_files.ExternalProtocol_pb2 import Status as _Status


class Test_Connecting_State(unittest.TestCase):

    def test_connecting_state_returns_without_exception(self):
        status = _Status(deviceState=_Status.CONNECTING)
        ES.check_device_is_in_connecting_state(status)

    def test_other_than_connecting_state_returns_exception(self):
        for state in [_Status.DISCONNECT, _Status.ERROR, _Status.RUNNING]:
            with self.assertRaises(ConnectSequenceFailure):
                ES.check_device_is_in_connecting_state(_Status(deviceState=state))


if __name__ == "__main__":  # pragma: no cover
    unittest.main(buffer=True)
