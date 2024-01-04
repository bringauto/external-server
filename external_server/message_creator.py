import sys

from external_server.structures import Buffer

sys.path.append("lib/fleet-protocol/protobuf/compiled/python")

import ExternalProtocol_pb2 as external_protocol
import InternalProtocol_pb2 as internal_protocol


class MessageCreator:
    """
    A class responsible for creating different types of messages for an external server.
    """

    @staticmethod
    def create_connect_response(
        session_id: str, connect_response_type: external_protocol.ConnectResponse.Type
    ) -> external_protocol.ExternalServer:
        """
        Creates a connect response message with the given session ID and response type.

        Args:
            session_id (str): The session ID for the connect response.
            connect_response_type (external_protocol.ConnectResponse.Type): The response type for the connect response.

        Returns:
            external_protocol.ExternalServer: An instance of the connect response message.
        """
        connect_response = external_protocol.ConnectResponse()
        connect_response.sessionId = session_id
        connect_response.type = connect_response_type
        sent_msg = external_protocol.ExternalServer()
        sent_msg.connectResponse.CopyFrom(connect_response)
        return sent_msg

    @staticmethod
    def create_status_response(
        session_id: str, message_counter: int
    ) -> external_protocol.ExternalServer:
        """
        Creates a status response message with the given session ID and message counter.

        Args:
            session_id (str): The session ID for the status response.
            message_counter (int): The message counter for the status response.

        Returns:
            external_protocol.ExternalServer: An instance of the status response message.
        """
        status_response = external_protocol.StatusResponse()
        status_response.sessionId = session_id
        status_response.type = external_protocol.StatusResponse.Type.OK
        status_response.messageCounter = message_counter
        sent_msg = external_protocol.ExternalServer()
        sent_msg.statusResponse.CopyFrom(status_response)
        return sent_msg

    @staticmethod
    def create_external_command(
        session_id: str, counter: int, device: internal_protocol.Device, command_data: bytes | None
    ) -> external_protocol.ExternalServer:
        """
        Creates an external command message with the given session ID, counter, device status, and command data.

        Args:
            session_id (str): The session ID for the external command.
            counter (int): The counter for the external command.
            status (internal_protocol.DeviceStatus): The device status for the external command.
            command_data (Buffer): The command data for the external command.

        Returns:
            external_protocol.ExternalServer: An instance of the external command message.
        """
        command = external_protocol.Command()
        command.sessionId = session_id
        command.messageCounter = counter
        command.deviceCommand.CopyFrom(
            MessageCreator._create_internal_command(device, command_data)
        )
        sent_msg = external_protocol.ExternalServer()
        sent_msg.command.CopyFrom(command)
        return sent_msg

    @staticmethod
    def _create_internal_command(
        device: internal_protocol.Device, command_data: bytes | None
    ) -> internal_protocol.DeviceCommand:
        device_command = internal_protocol.DeviceCommand()

        if device == None:
            tmp_device = internal_protocol.Device()
            device_command.device.CopyFrom(tmp_device)
        else:
            device_command.device.CopyFrom(device)

        if command_data == None:
            device_command.commandData = bytes()
        else:
            device_command.commandData = command_data

        return device_command
