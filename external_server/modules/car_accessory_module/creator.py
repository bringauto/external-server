import json

from external_server.modules.message_creator import MessageCreator
import external_server.protobuf.InternalProtocol_pb2 as internal_protocol
import external_server.protobuf.ExternalProtocol_pb2 as external_protocol


class CarAccessoryCreator(MessageCreator):

    def create_command(self, session_id: str, counter: int,
                       status: internal_protocol.DeviceStatus) -> external_protocol.Command:
        statusData = json.loads(status.statusData)
        device_command = internal_protocol.DeviceCommand()
        device_command.commandData = json.dumps({"lit_up": True if statusData["pressed"] else False}).encode()
        command = external_protocol.Command()
        command.sessionId = session_id
        command.messageCounter = counter
        command.device.CopyFrom(status.device)
        command.deviceCommand.CopyFrom(device_command)
        return command
