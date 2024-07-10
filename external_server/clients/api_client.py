import ctypes as ct
import threading
import sys

sys.path.append("lib/fleet-protocol/protobuf/compiled/python")

from InternalProtocol_pb2 import (  # type: ignore
    Device as _Device,
)
from external_server.utils import check_file_exists
from external_server.models.structures import (
    Config,
    KeyValue,
    Buffer,
    DeviceIdentification,
    DisconnectTypes,
)
from external_server.config import ModuleConfig
from external_server.models.structures import GeneralErrorCodes as _GeneralErrorCodes


class ExternalServerApiClient:
    """External server API functions wrapper

    This class is wrapper around External server API functions (further API). It
    retains context, created by init and uses it with other functions. It also take
    care about API's specific structures like Buffer and device_identification
    (memory management, converting from Protobuf messages or bytes). So methods,
    which represents every'API function, is called with Protobuf messages. Then
    these structures are properly converted and function from API is called. This
    class also implements lock on every API function (except wait_for_command)
    according to Fleet protocol.
    Class also implements some helper functions like deallocate, get_module_number
    and is_device_type_supported.

    """
    def __init__(self, module_config: ModuleConfig, company_name: str, car_name: str) -> None:
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
        self._lib_path = module_config.lib_path.absolute().as_posix()
        self._config = {"company_name": company_name, "car_name": car_name}
        self._config.update(module_config.config)
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
        """Initializes the library and sets the context."""
        if not check_file_exists(self._lib_path):
            raise FileNotFoundError(self._lib_path)
        self._library = ct.cdll.LoadLibrary(self._lib_path)
        self._type_all_function()
        self._set_context()

    def _set_context(self):
        """Sets the context based on the module configuration."""
        if self._config is not None and len(self._config):
            key_value_array = (KeyValue * len(self._config))()

            for i, key in enumerate(self._config):
                key_bytes = key.encode("utf-8")
                value_bytes = self._config[key].encode("utf-8")
                key_value_array[i] = KeyValue(
                    Buffer(data=ct.c_char_p(key_bytes), size=len(key_bytes)),
                    Buffer(data=ct.c_char_p(value_bytes), size=len(value_bytes)),
                )

            config_struct = Config(key_value_array, len(self._config))
        else:
            config_struct = Config(None, 0)

        with self._lock:
            self._context = self._library.init(config_struct)

    def _type_all_function(self) -> None:
        """
        Defines the argument types and return types for all the library functions.
        """
        self._library.get_module_number.argtypes = []
        self._library.get_module_number.restype = ct.c_int
        self._library.deallocate.argtypes = [ct.POINTER(Buffer)]
        self._library.deallocate.restype = ct.c_void_p
        self._library.init.argtypes = [Config]
        self._library.init.restype = ct.c_void_p
        self._library.device_connected.argtypes = [DeviceIdentification, ct.c_void_p]
        self._library.device_connected.restype = ct.c_int
        self._library.device_disconnected.argtypes = [
            DisconnectTypes,
            DeviceIdentification,
            ct.c_void_p,
        ]
        self._library.device_disconnected.restype = ct.c_int
        self._library.forward_status.argtypes = [Buffer, DeviceIdentification, ct.c_void_p]
        self._library.forward_status.restype = ct.c_int
        self._library.forward_error_message.argtypes = [Buffer, DeviceIdentification, ct.c_void_p]
        self._library.forward_error_message.restype = ct.c_int
        self._library.wait_for_command.argtypes = [ct.c_int, ct.c_void_p]
        self._library.wait_for_command.restype = ct.c_int
        self._library.pop_command.argtypes = [
            ct.POINTER(Buffer),
            ct.POINTER(DeviceIdentification),
            ct.c_void_p,
        ]
        self._library.pop_command.restype = ct.c_int
        self._library.command_ack.argtypes = [Buffer, DeviceIdentification, ct.c_void_p]
        self._library.command_ack.restype = ct.c_int
        self._library.destroy.argtypes = [ct.POINTER(ct.c_void_p)]
        self._library.destroy.restype = ct.c_int
        self._library.is_device_type_supported.argtypes = [ct.c_uint]
        self._library.is_device_type_supported.restype = ct.c_int

    def destroy(self) -> int:
        """
        Destroys the library and cleans up.
        """
        with self._lock:
            con = ct.c_void_p(self._context)
            return self._library.destroy(ct.pointer(con))

    def device_initialized(self) -> bool:
        """
        Checks if device is initialized.

        Returns
        -------
        bool
            True if device is initialized, False otherwise.
        """
        return self._context is not None

    def device_connected(self, device: _Device) -> int:
        """
        Handles device connection by creating the device identification and calling the library function.

        Parameters
        ----------
        device: Device
            The device object.

        Returns
        -------
        int
            The result of the library function call.
        """
        device_identification = self._create_device_identification(device)
        with self._lock:
            return self._library.device_connected(device_identification, self._context)

    def device_disconnected(self, disconnect_types: DisconnectTypes, device: _Device) -> int:
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
            return self._library.device_disconnected(
                disconnect_types, device_identification, self._context
            )

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

    def forward_status(self, device: _Device, status_bytes: bytes) -> int:
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
            return self._library.forward_status(status_buffer, device_identification, self._context)

    def forward_error_message(self, device: _Device, error_bytes: bytes) -> int:
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
        device_identification = self._create_device_identification(device)
        error_buffer = Buffer(data=error_bytes, size=len(error_bytes))
        with self._lock:
            return self._library.forward_error_message(
                error_buffer, device_identification, self._context
            )

    def wait_for_command(self, timeout: int) -> int:
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
        return self._library.wait_for_command(timeout, self._context)

    def pop_command(self) -> [bytes, _Device, int]:
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
            rc = self._library.pop_command(
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

    def command_ack(self, command_data: bytes, device: _Device) -> int:
        """Calls command_ack function from API"""
        device_id = self._create_device_identification(device)
        with self._lock:
            command_buffer = Buffer(command_data, len(command_data))
            return self._library.command_ack(command_buffer, device_id, self._context)

    def deallocate(self, buffer: Buffer) -> None:
        self._library.deallocate(buffer)

    def get_module_number(self) -> int:
        return self._library.get_module_number()

    def is_device_type_supported(self, device_type: int) -> bool:
        code = self._library.is_device_type_supported(ct.c_uint(device_type))
        return code == _GeneralErrorCodes.OK
