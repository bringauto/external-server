import sys
from typing import Optional

sys.path.append("lib/fleet-protocol/protobuf/compiled/python")

from InternalProtocol_pb2 import (  # type: ignore
    Device as _Device,
    DeviceCommand as _DeviceCommand,
    DeviceStatus as DeviceStatus,
)
from ExternalProtocol_pb2 import (  # type: ignore
    Command as _Command,
    Connect as _Connect,
    CommandResponse as _CommandResponse,
    ConnectResponse as _ConnectResponse,
    ExternalClient as _ExternalClientMsg,
    ExternalServer as ExternalServerMsg,
    Status as _Status,
    StatusResponse as _StatusResponse,
)


def connect_response(session_id: str, response_type: _ConnectResponse.Type) -> ExternalServerMsg:
    """Creates a connect response message with the given session ID and response type.

    Args:
        session_id (str): The session ID for the connect response.
        response_type (_ConnectResponse.Type): The response type for the connect response.

    Returns:
        ExternalServerMsg: An instance of ExternalServerMsg containing the connect response message.
    """
    connect_response = _ConnectResponse()
    connect_response.sessionId = session_id
    connect_response.type = response_type
    sent_msg = ExternalServerMsg()
    sent_msg.connectResponse.CopyFrom(connect_response)
    return sent_msg


def status_response(session_id: str, message_counter: int) -> ExternalServerMsg:
    """
    Creates a status response message with the given session ID and message counter.

    Args:
        session_id (str): The session ID for the status response.
        message_counter (int): The message counter for the status response.

    Returns:
        ExternalServerMsg: An instance of the status response message.
    """
    status_response = _StatusResponse()
    status_response.sessionId = session_id
    status_response.type = _StatusResponse.OK
    status_response.messageCounter = message_counter
    sent_msg = ExternalServerMsg()
    sent_msg.statusResponse.CopyFrom(status_response)
    return sent_msg


def command(
    session_id: str, counter: int, device: _Device, data: bytes = bytes()
) -> ExternalServerMsg:
    """Creates an external command with the session ID, counter, device status and data.

    Args:
        session_id (str): The session ID for the external command.
        counter (int): The counter for the external command.
        device (_Device): The target device for the external command.
        data (bytes): The command data for the external command.

    Returns:
        ExternalServerMsg: An instance of the external command message.
    """
    command = _Command()
    command.sessionId = session_id
    command.messageCounter = counter
    command.deviceCommand.CopyFrom(_DeviceCommand(device=device, commandData=data))
    sent_msg = ExternalServerMsg()
    sent_msg.command.CopyFrom(command)
    return sent_msg


def connect_msg(session_id: str, company: str, devices: list[_Device]) -> _ExternalClientMsg:
    return _ExternalClientMsg(
        connect=_Connect(sessionId=session_id, company=company, devices=devices)
    )


def cmd_response(
    session_id: str, counter: int, type: _CommandResponse.Type = _CommandResponse.OK
) -> _ExternalClientMsg:
    return _ExternalClientMsg(
        commandResponse=_CommandResponse(sessionId=session_id, type=type, messageCounter=counter)
    )


def status(
    session_id: str,
    state: _Status.DeviceState,
    counter: int,
    status: DeviceStatus,
    error_message: Optional[bytes] = None,
) -> _ExternalClientMsg:

    status_msg = _Status(
        sessionId=session_id,
        deviceState=state,
        messageCounter=counter,
        deviceStatus=status,
        errorMessage=error_message,
    )
    return _ExternalClientMsg(status=status_msg)
