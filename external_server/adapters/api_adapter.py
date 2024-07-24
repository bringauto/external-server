import ctypes as ct
import threading
import sys
import logging.config
import json
import os

sys.path.append("lib/fleet-protocol/protobuf/compiled/python")

from InternalProtocol_pb2 import (  # type: ignore
    Device as _Device,
)
from external_server.models.structures import (
    Config,
    KeyValue,
    Buffer,
    DeviceIdentification,
    DisconnectTypes,
)
from external_server.config import ModuleConfig
from external_server.models.structures import (
    GeneralErrorCode as _GeneralErrorCode,
    ReturnCode,
)


_logger = logging.getLogger(__name__)
with open("./config/logging.json", "r") as f:
    logging.config.dictConfig(json.load(f))


class APIClientAdapter:
    """A wrapper around External server API functions (further API).

    It retains context, created by init and uses it with other functions. It also take
    care about API's specific structures like Buffer and device_identification
    (memory management, converting from Protobuf messages or bytes). So methods,
    which represents every'API function, is called with Protobuf messages. Then
    these structures are properly converted and function from API is called. This
    class also implements lock on every API function (except wait_for_command)
    according to Fleet protocol.
    Class also implements some helper functions like deallocate, get_module_number
    and is_device_type_supported.
    """

    def __init__(self, config: ModuleConfig, company: str, car: str) -> None:
        """Initializes API Wrapper for Module

        Parameters
        ----------
        module_config : dict
            Json config for specific module

        company_name : str
            company name from Json config, which will be forwarded as first key-value to API

        car_name : str
            car name from Json config, which will be forwarded as second key-value to API
        """
        self._lib_path = config.lib_path.absolute().as_posix()
        self._config = {"company_name": company, "car_name": car}
        self._config.update(config.config)
        self._library = None
        self._context = None
        self._lock = threading.Lock()

    @property
    def library(self):
        return self._library

    @property
    def context(self):
        return self._context

    def init(self) -> None:
        """Initializes the library and sets the context.

        Error is raised if the library is not found or the context is not set.
        """
        if not os.path.isfile(self._lib_path):
            raise FileNotFoundError(self._lib_path)
        self._library = ct.cdll.LoadLibrary(self._lib_path)  # type: ignore
        self._type_all_function()
        self._set_context()
        if not self._context:
            raise RuntimeError("API Client initialization failed.")

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

    def destroy(self) -> int:
        """
        Destroys the library and cleans up.
        """
        with self._lock:
            con = ct.c_void_p(self._context)
            return self._library.destroy(ct.pointer(con))  # type: ignore

    def device_initialized(self) -> bool:
        """
        Checks if device is initialized.

        Returns
        -------
        bool
            True if device is initialized, False otherwise.
        """
        return self._context is not None

    def device_connected(self, device: _Device) -> ReturnCode:
        """Handles device connection by creating the device identification and calling
        the library function.

        Parameters
        ----------
        device: Device
            The device object.

        Returns
        -------
        int
            The result of the library function call.
        """
        device.priority = 0  # Set priority to zero - the external server must ignore the priority.
        device_identification = self._create_device_identification(device)
        with self._lock:
            return self._library.device_connected(device_identification, self._context)  # type: ignore

    def device_disconnected(self, disconnect_types: DisconnectTypes, device: _Device) -> ReturnCode:
        """
        Handles device disconnection by creating the device identification and calling the library function.

        Parameters
        ----------
        disconnect_types: DisconnectTypes
            Type of disconnection

        device: Device
            The device object.

        Returns
        -------
        int
            The result of the library function call.
        """
        device_identification = self._create_device_identification(device)
        with self._lock:
            code = self._library.device_disconnected(  # type: ignore
                disconnect_types, device_identification, self._context
            )
            self._check_device_disconnected_code(device.module, code)
            return code

    def _create_device_identification(self, device: _Device) -> DeviceIdentification:
        """
        Creates a DeviceIdentification structure based on the provided device object.

        Parameters
        ----------
        device: Device
            The device object.

        Returns
        -------
        DeviceIdentification
            The created DeviceIdentification structure.
        """
        device_role = device.deviceRole.encode("utf-8")
        device_role_buffer = Buffer(data=device_role, size=len(device_role))
        device_name = device.deviceName.encode("utf-8")
        device_name_buffer = Buffer(data=device_name, size=len(device_name))

        return DeviceIdentification(
            module=device.module,
            device_type=device.deviceType,
            device_role=device_role_buffer,
            device_name=device_name_buffer,
            priority=device.priority,
        )

    def _create_protobuf_device(self, device_id: DeviceIdentification) -> _Device:
        device = _Device()
        device.module = device_id.module
        device.priority = device_id.priority
        device.deviceType = device_id.device_type
        if not device_id.device_role.data or device_id.device_role.size == 0:
            device.deviceRole = ""
        else:
            device.deviceRole = device_id.device_role.data[: device_id.device_role.size].decode(
                "utf-8"
            )

        if not device_id.device_name.data or device_id.device_name.size == 0:
            device.deviceName = ""
        else:
            device.deviceName = device_id.device_name.data[: device_id.device_name.size].decode(
                "utf-8"
            )

        return device

    def forward_status(self, device: _Device, status_bytes: bytes) -> ReturnCode:
        """
        Forwards a status update by creating the device identification and status buffer,
        and calling the library function.

        Parameters
        ----------
        device: Device
            The device object.

        status_bytes: bytes
            Bytes of status message.

        Returns
        -------
        int
            The result of the library function call.
        """
        device_identification = self._create_device_identification(device)
        status_buffer = Buffer(data=status_bytes, size=len(status_bytes))
        with self._lock:
            code = self._library.forward_status(  # type: ignore
                status_buffer, device_identification, self._context
            )
            self._check_forward_status_code(device.module, code)
            return code

    def forward_error_message(self, device: _Device, error_bytes: bytes) -> ReturnCode:
        """
        Forwards an error message by creating the device identification and status buffer,
        and calling the library function.

        Parameters
        ----------
        device: Device
            The device object.

        error_bytes: bytes
            Bytes of error message.

        Returns
        -------
        int
            The result of the library function call.
        """
        assert isinstance(error_bytes, bytes)
        device_identification = self._create_device_identification(device)
        error_buffer = Buffer(data=error_bytes, size=len(error_bytes))
        with self._lock:
            code = self._library.forward_error_message(  # type: ignore
                error_buffer, device_identification, self._context
            )
            self._check_forward_error_message_code(device.module, code)
            return code

    def wait_for_command(self, timeout: int) -> ReturnCode:
        """
        Waits for a command from the library with the specified timeout.

        Parameters
        ----------
        timeout: int
            The timeout in milliseconds.

        Returns
        -------
        int
            The result of the library function call.
        """
        return self._library.wait_for_command(timeout, self._context)  # type: ignore

    def pop_command(self) -> tuple[bytes, _Device, ReturnCode]:
        """
        Gets a command from the library by creating the device identification and calling the library function.

        Returns
        -------
        bytes
            Command bytes returned from API.
        Device
            Device, for which the command is intended.
        int
            Return value of API function.
        """
        command_buffer = Buffer(ct.c_char_p(), 0)
        device_identification = DeviceIdentification(
            0, 0, Buffer(ct.c_char_p(), 0), Buffer(ct.c_char_p()), 0
        )
        with self._lock:
            rc = self._library.pop_command(  # type: ignore
                ct.byref(command_buffer), ct.byref(device_identification), self._context
            )
        device = self._create_protobuf_device(device_identification)
        self.deallocate(device_identification.device_role)
        self.deallocate(device_identification.device_name)
        if not command_buffer or not command_buffer.data or command_buffer.size == 0:
            command_bytes = bytes()
        else:
            command_bytes = bytes(command_buffer.data)[: command_buffer.size]
        self.deallocate(command_buffer)

        return command_bytes, device, rc

    def command_ack(self, command_data: bytes, device: _Device) -> ReturnCode:
        """Calls command_ack function from API"""
        device_id = self._create_device_identification(device)
        with self._lock:
            command_buffer = Buffer(command_data, len(command_data))
            code = self._library.command_ack(command_buffer, device_id, self._context)  # type: ignore
            self._check_command_ack_code(device.module, code)
            return code

    def deallocate(self, buffer: Buffer) -> None:
        self._library.deallocate(buffer)  # type: ignore

    def get_module_number(self) -> int:
        return self._library.get_module_number()  # type: ignore

    def is_device_type_supported(self, device_type: int) -> bool:
        code = self._library.is_device_type_supported(ct.c_uint(device_type))  # type: ignore
        return code == _GeneralErrorCode.OK

    @staticmethod
    def _check_forward_status_code(module_id: int, code: int) -> None:
        if code != _GeneralErrorCode.OK:
            _logger.error(f"Module {module_id}: Error in forward_status function, code: {code}")

    @staticmethod
    def _check_forward_error_message_code(module_id: int, code: int) -> None:
        if code != _GeneralErrorCode.OK:
            _logger.error(
                f"Module {module_id}: Error in forward_error_message function, code: {code}"
            )

    @staticmethod
    def _check_device_disconnected_code(module_id: int, code: int) -> None:
        if code != _GeneralErrorCode.OK:
            _logger.error(
                f"Module {module_id}: Error in device_disconnected function, code: {code}"
            )

    @staticmethod
    def _check_command_ack_code(module_id: int, code: int) -> None:
        if code != _GeneralErrorCode.OK:
            _logger.error(f"Module {module_id}: Error in command_ack function, code: {code}")
