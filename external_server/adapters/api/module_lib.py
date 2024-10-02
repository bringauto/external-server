import ctypes as ct
import sys
from typing import Any
import os
import threading

sys.path.append("lib/fleet-protocol/protobuf/compiled/python")

from external_server.models.structures import (
    Config,
    Buffer,
    DeviceIdentification,
    DisconnectTypes,
)
from external_server.models.structures import (
    Config,
    KeyValue,
)


def empty_command_buffer() -> Buffer:
    return Buffer(ct.c_char_p(), 0)


def empty_device_identification() -> DeviceIdentification:
    return DeviceIdentification(0, 0, Buffer(ct.c_char_p(), 0), Buffer(ct.c_char_p()), 0)


class ModuleLibrary:

    def __init__(self, lib_path: str, config: dict[str, Any]):
        self._config = config
        self._lib_path = lib_path
        self._library = None
        self._context = None
        self._lock = threading.Lock()

    @property
    def context(self) -> ct.c_void_p | None:
        return self._context

    @property
    def library(self) -> ct.CDLL:
        if not self._library:
            raise RuntimeError("API Client not initialized")
        return self._library

    def device_disconnected(
        self, disconnect_type: DisconnectTypes, device: DeviceIdentification
    ) -> int:
        return int(self.library.device_disconnected(disconnect_type, device, self._context))

    def device_connected(self, device: DeviceIdentification) -> int:
        with self._lock:
            return int(self.library.device_connected(device, self._context))

    def command_ack(self, buffer: Buffer, device: DeviceIdentification) -> int:
        return int(self.library.command_ack(buffer, device, self._context))

    def destroy(self) -> int:
        with self._lock:
            con = ct.c_void_p(self._context)
            return self._library.destroy(ct.pointer(con))  # type: ignore

    def deallocate(self, buffer: Buffer) -> None:
        self.library.deallocate(buffer)

    def forward_error_message(self, buffer: Buffer, device: DeviceIdentification) -> int:
        return int(self.library.forward_error_message(buffer, device, self._context))

    def forward_status(self, buffer: Buffer, device: DeviceIdentification) -> int:
        return int(self.library.forward_status(buffer, device, self._context))

    def get_module_number(self) -> int:
        return int(self.library.get_module_number())

    def init(self) -> ct.c_void_p:
        if not os.path.isfile(self._lib_path):
            raise FileNotFoundError(self._lib_path)
        self._library = ct.cdll.LoadLibrary(self._lib_path)  # type: ignore
        self._type_all_function()
        self._set_context()
        if not self._context:
            raise RuntimeError("API Client initialization failed.")

    def is_device_type_supported(self, device_type: int) -> int:
        return int(self.library.is_device_type_supported(ct.c_uint(device_type)))

    def pop_command(self, cmd_buffer: Buffer, device: DeviceIdentification) -> int:
        with self._lock:
            return int(
                self.library.pop_command(ct.byref(cmd_buffer), ct.byref(device), self._context)
            )

    def wait_for_command(self, timeout: int) -> int:
        return int(self.library.wait_for_command(timeout, self._context))

    def _set_context(self):
        """Sets the context based on the module configuration."""
        key_value_array = (KeyValue * len(self._config))()
        for i, key in enumerate(self._config):
            key_bytes = key.encode("utf-8")
            value_bytes = self._config[key].encode("utf-8")
            key_value_array[i] = KeyValue(
                Buffer(data=ct.c_char_p(key_bytes), size=len(key_bytes)),
                Buffer(data=ct.c_char_p(value_bytes), size=len(value_bytes)),
            )
        config_struct = Config(key_value_array, len(self._config))
        with self._lock:
            self._context = self._library.init(config_struct)

    def _type_all_function(self) -> None:  # type: ignore
        """Defines the argument types and return types for all the library functions."""
        self._library.get_module_number.argtypes = []  # type: ignore
        self._library.get_module_number.restype = ct.c_int  # type: ignore
        self._library.deallocate.argtypes = [ct.POINTER(Buffer)]  # type: ignore
        self._library.deallocate.restype = ct.c_void_p  # type: ignore
        self._library.init.argtypes = [Config]  # type: ignore
        self._library.init.restype = ct.c_void_p  # type: ignore
        self._library.device_connected.argtypes = [DeviceIdentification, ct.c_void_p]  # type: ignore
        self._library.device_connected.restype = ct.c_int  # type: ignore
        self._library.device_disconnected.argtypes = [  # type: ignore  # type: ignore
            DisconnectTypes,
            DeviceIdentification,
            ct.c_void_p,
        ]
        self._library.device_disconnected.restype = ct.c_int  # type: ignore
        self._library.forward_status.argtypes = [Buffer, DeviceIdentification, ct.c_void_p]  # type: ignore
        self._library.forward_status.restype = ct.c_int  # type: ignore
        self._library.forward_error_message.argtypes = [Buffer, DeviceIdentification, ct.c_void_p]  # type: ignore
        self._library.forward_error_message.restype = ct.c_int  # type: ignore
        self._library.wait_for_command.argtypes = [ct.c_int, ct.c_void_p]  # type: ignore
        self._library.wait_for_command.restype = ct.c_int  # type: ignore
        self._library.pop_command.argtypes = [  # type: ignore
            ct.POINTER(Buffer),
            ct.POINTER(DeviceIdentification),
            ct.c_void_p,
        ]
        self._library.pop_command.restype = ct.c_int  # type: ignore
        self._library.command_ack.argtypes = [Buffer, DeviceIdentification, ct.c_void_p]  # type: ignore
        self._library.command_ack.restype = ct.c_int  # type: ignore
        self._library.destroy.argtypes = [ct.POINTER(ct.c_void_p)]  # type: ignore
        self._library.destroy.restype = ct.c_int  # type: ignore
        self._library.is_device_type_supported.argtypes = [ct.c_uint]  # type: ignore
        self._library.is_device_type_supported.restype = ct.c_int  # type: ignore
