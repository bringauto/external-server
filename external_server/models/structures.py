import ctypes as ct
from enum import IntEnum
import dataclasses

from InternalProtocol_pb2 import (  # type: ignore
    Device as _Device,
    DeviceCommand as _DeviceCommand,
)
from ExternalProtocol_pb2 import (  # type: ignore
    Command as _Command,
    ExternalServer as _ExternalServerMsg,
)


ReturnCode = int
ReturnedFromAPIFlag = bool
Counter = int


class TimeoutType(IntEnum):
    SESSION_TIMEOUT = 0
    STATUS_TIMEOUT = 1
    COMMAND_RESPONSE_TIMEOUT = 2


# Enum taken from general_error_codes.h in Fleet protocol,
# must be kept updated with the current version of the Fleet protocol


class GeneralErrorCode(IntEnum):
    OK = 0  # Routine execution succeed
    NOT_OK = -1  # Routine execution did not succeed
    RESERVED = -10  # Codes from -1 to RESERVED are reserved as General purpose errors


# Enum taken from external_server_structures.h in Fleet protocol,
# must be kept updated with the current version of the Fleet protocol


class EsErrorCode(IntEnum):
    CONTEXT_INCORRECT = GeneralErrorCode.RESERVED - 1
    TIMEOUT = GeneralErrorCode.RESERVED - 2


# Enum taken from external_server_structures.h in Fleet protocol,
# must be kept updated with the current version of the Fleet protocol


class DisconnectTypes(IntEnum):
    announced = 0
    timeout = 1
    error = 2

    @classmethod
    def from_param(cls, obj):
        return int(obj)


class Buffer(ct.Structure):
    _fields_ = [("data", ct.c_char_p), ("size", ct.c_size_t)]


class DeviceIdentification(ct.Structure):
    _fields_ = [
        ("module", ct.c_int),
        ("device_type", ct.c_uint),
        ("device_role", Buffer),
        ("device_name", Buffer),
        ("priority", ct.c_uint),
    ]


class KeyValue(ct.Structure):
    _fields_ = [("key", Buffer), ("value", Buffer)]


class Config(ct.Structure):
    _fields_ = [("parameters", ct.POINTER(KeyValue)), ("size", ct.c_size_t)]


@dataclasses.dataclass(frozen=True)
class HandledCommand:
    """This class binds Command message with the flag denoting if the command was returned
    by get_command API function or generated by the server.
    """

    data: bytes
    device: _Device
    counter: Counter = -1
    from_api: ReturnedFromAPIFlag = False

    def copy(self) -> "HandledCommand":
        # do not set the counter to prevent unexpected match between two commands counters
        return HandledCommand(
            data=self.data, device=self.device, from_api=self.from_api
        )

    def external_command(self, session_id: str) -> _ExternalServerMsg:
        """Return the command as ExternalServer message."""
        try:
            if self.counter < 0:
                raise ValueError
            command = _Command(
                sessionId=session_id,
                messageCounter=self.counter,
                deviceCommand=_DeviceCommand(device=self.device, commandData=self.data),
            )
            return _ExternalServerMsg(command=command)
        except ValueError as e:
            raise ValueError("Incorrect command data. Counter value is not set.") from e
        except Exception as e:
            raise ValueError(f"Incorrect command data. {e.args[0]}") from e

    def update_counter_value(self, counter: Counter) -> None:
        """Set the counter value of the command."""
        self.__dict__["counter"] = counter
