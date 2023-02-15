import json

from external_server.modules.message_creator import MessageCreator
import external_server.protobuf.InternalProtocol_pb2 as internal_protocol


class CarAccessoryCreator(MessageCreator):
    def _create_internal_command(
        self, status: internal_protocol.DeviceStatus
    ) -> internal_protocol.DeviceCommand:
        status_data = json.loads(status.statusData)
        device_command = internal_protocol.DeviceCommand()
        device_command.commandData = json.dumps(
            {"lit_up": status_data["pressed"]}
        ).encode()
        return device_command
