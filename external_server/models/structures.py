from __future__ import annotations
import ctypes as ct
from enum import IntEnum
import dataclasses

from InternalProtocol_pb2 import Device as _Device


class TimeoutType(IntEnum):
    SESSION_TIMEOUT = 0
    MESSAGE_TIMEOUT = 1
    COMMAND_TIMEOUT = 2


# Enum taken from general_error_codes.h in Fleet protocol,
# must be kept updated with the current version of the Fleet protocol


# enum general_error_codes_enum {
#   OK       = 0,   /// Routine execution succeed
#   NOT_OK   = -1,  /// Routine execution does not succeed
#   RESERVED = -10, /// Codes from -1 to RESERVED are reserved as General purpose errors
# };
class GeneralErrorCodes(IntEnum):
    OK = 0
    NOT_OK = -1
    RESERVED = -10


# Enum taken from external_server_structures.h in Fleet protocol,
# must be kept updated with the current version of the Fleet protocol


# enum es_error_codes {
# 	CONTEXT_INCORRECT = -11,
# 	TIMEOUT_OCCURRED = -12,
# };
class EsErrorCodes(IntEnum):
    CONTEXT_INCORRECT = GeneralErrorCodes.RESERVED - 1
    TIMEOUT_OCCURRED = GeneralErrorCodes.RESERVED - 2


# Enum taken from external_server_structures.h in Fleet protocol,
# must be kept updated with the current version of the Fleet protocol


# enum disconnect_types {
# 	announced = 0,
# 	timeout = 1,
# 	error = 2
# };
class DisconnectTypes(IntEnum):
    announced = 0
    timeout = 1
    error = 2

    @classmethod
    def from_param(cls, obj):
        return int(obj)


# struct buffer {
# 	void *data;
# 	size_t size;
# };
class Buffer(ct.Structure):
    _fields_ = [("data", ct.c_char_p), ("size", ct.c_size_t)]


# struct device_identification {
# 	int device_type;
# 	char device# 	char device_name[NAME_LENGTH];
# };_role[NAME_LENGTH];

class DeviceIdentification(ct.Structure):
    _fields_ = [
        ("module", ct.c_int),
        ("device_type", ct.c_uint),
        ("device_role", Buffer),
        ("device_name", Buffer),
        ("priority", ct.c_uint),
    ]


# struct key_value {
# 	buffer key;
# 	buffer value;
# };
class KeyValue(ct.Structure):
    _fields_ = [("key", Buffer), ("value", Buffer)]


# struct config {
# 	key_value* parameters;
# 	size_t size;
# };
class Config(ct.Structure):
    _fields_ = [("parameters", ct.POINTER(KeyValue)), ("size", ct.c_size_t)]


@dataclasses.dataclass(frozen=True)
class DevicePy:
    module_id: int
    type: int
    role: str
    name: str
    priority: int

    def __eq__(self, other: object):
        if isinstance(other, DevicePy):
            return (
                self.module_id == other.module_id
                and self.type == other.type
                and self.role == other.role
            )
        elif isinstance(other, _Device):
            return (
                self.module_id == other.module
                and self.type == other.deviceType
                and self.role == other.deviceRole
            )
        else:
            raise NotImplementedError

    def to_device(self) -> _Device:
        return _Device(
            module=self.module_id,
            deviceType=self.type,
            deviceRole=self.role,
            deviceName=self.name,
            priority=self.priority,
        )

    @staticmethod
    def from_device(device: _Device) -> DevicePy:
        return DevicePy(
            module_id=device.module,
            type=device.deviceType,
            role=device.deviceRole,
            name=device.deviceName,
            priority=device.priority,
        )