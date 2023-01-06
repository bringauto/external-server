import json

from external_server.modules.message_creator import MessageCreator
import external_server.protobuf.InternalProtocol_pb2 as internal_protocol
import external_server.protobuf.ExternalProtocol_pb2 as external_protocol


class CarAccessoryCreator(MessageCreator):

    def create_command(self, status_bytes: bytes) -> external_protocol.Command:
        status = json.loads(status_bytes)
        device_command = internal_protocol.DeviceCommand()
        device_command.commandData = json.dumps({"lit_up": True if status["pressed"] else False}).encode()
        command = external_protocol.Command()
        command.deviceCommand.CopyFrom(device_command)
        return command
