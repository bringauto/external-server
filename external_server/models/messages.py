import sys
from typing import Optional, Literal

sys.path.append("lib/fleet-protocol/protobuf/compiled/python")

from InternalProtocol_pb2 import (  # type: ignore
    Device as _Device,
    DeviceCommand as _DeviceCommand,
    DeviceStatus as _DeviceStatus,
)
from ExternalProtocol_pb2 import (  # type: ignore
    Command as _Command,
    Connect as _Connect,
    CommandResponse as _CommandResponse,
    ConnectResponse as _ConnectResponse,
    ExternalClient as _ExternalClientMsg,
    ExternalServer as _ExternalServerMsg,
    Status as _Status,
    StatusResponse as _StatusResponse,
)


def connect_response(session_id: str, response_type: _ConnectResponse.Type) -> _ExternalServerMsg:
    """Creates a connect response message with the given session ID and response type.

    Args:
        session_id (str): The session ID for the connect response.
        connect_response_type (ConnectResponse.Type): The response type for the connect response.

    Returns:
        ExternalServer: An instance of the connect response message.
    """
    connect_response = _ConnectResponse()
    connect_response.sessionId = session_id
    connect_response.type = response_type
    sent_msg = _ExternalServerMsg()
    sent_msg.connectResponse.CopyFrom(connect_response)
    return sent_msg


def status_response(session_id: str, message_counter: int) -> _ExternalServerMsg:
    """
    Creates a status response message with the given session ID and message counter.

    Args:
        session_id (str): The session ID for the status response.
        message_counter (int): The message counter for the status response.

    Returns:
        ExternalServer: An instance of the status response message.
    """
    status_response = _StatusResponse()
    status_response.sessionId = session_id
    status_response.type = _StatusResponse.OK
    status_response.messageCounter = message_counter
    sent_msg = _ExternalServerMsg()
    sent_msg.statusResponse.CopyFrom(status_response)
    return sent_msg


def command(
    session_id: str, counter: int, device: _Device, data: bytes = bytes()
) -> _ExternalServerMsg:
    """Creates an external command with the session ID, counter, device status and data.

    Args:
        session_id (str): The session ID for the external command.
        counter (int): The counter for the external command.
        status (DeviceStatus): The device status for the external command.
        command_data (Buffer): The command data for the external command.

    Returns:
        ExternalServer: An instance of the external command message.
    """
    command = _Command()
    command.sessionId = session_id
    command.messageCounter = counter
    command.deviceCommand.CopyFrom(_DeviceCommand(device=device, commandData=data))
    sent_msg = _ExternalServerMsg()
    sent_msg.command.CopyFrom(command)
    return sent_msg


def connect_msg(session_id: str, company: str, car: str, devices: list[_Device]) -> _ExternalClientMsg:
    return _ExternalClientMsg(
        connect=_Connect(sessionId=session_id, company=company, vehicleName=car, devices=devices)
    )


def cmd_response(session_id: str, counter: int, type: _CommandResponse.Type) -> _ExternalClientMsg:
    return _ExternalClientMsg(
        commandResponse=_CommandResponse(sessionId=session_id, type=type, messageCounter=counter)
    )


def status(
    session_id: str,
    state: _Status.DeviceState,
    counter: int,
    status: _DeviceStatus,
    error_message: Optional[bytes] = None,
) -> _ExternalClientMsg:

    assert isinstance(error_message, bytes) or error_message is None
    status=_Status(
        sessionId=session_id,
        deviceState=state,
        messageCounter=counter,
        deviceStatus=status,
        errorMessage=error_message,
    )
    return _ExternalClientMsg(status=status)

