from typing import Optional
import sys

sys.path.append("lib/fleet-protocol/protobuf/compiled/python")

from InternalProtocol_pb2 import (  # type: ignore
    Device as _Device,
    DeviceStatus as _DeviceStatus
)
from ExternalProtocol_pb2 import (  # type: ignore
    CommandResponse as _CommandResponse,
    Connect as _Connect,
    Status as _Status,
    ExternalClient as _ExternalClientMsg,
)


def device_repr(device: _Device) -> str:
    return f"{device.module}/{device.deviceType}/{device.deviceRole}/{device.deviceName}"


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

