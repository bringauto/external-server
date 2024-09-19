import threading
import sys

sys.path.append("lib/fleet-protocol/protobuf/compiled/python")

from InternalProtocol_pb2 import (  # type: ignore
    Device as _Device,
)
from ExternalProtocol_pb2 import Status as _Status  # type: ignore
from external_server.models.structures import (
    Buffer,
    DeviceIdentification,
    DisconnectTypes,
)
from external_server.config import ModuleConfig, configure_logging
from external_server.models.structures import (
    GeneralErrorCode as _GeneralErrorCode,
    ReturnCode,
)
from external_server.models.devices import device_repr
from external_server.adapters.api.module_lib import (
    empty_command_buffer as _empty_command_buffer,
    empty_device_identification as _empty_device_identification,
    ModuleLibrary as _ModuleLibrary,
)
from external_server.logs import CarLogger as _CarLogger


_logger = _CarLogger(__name__)


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
        self._library = _ModuleLibrary(
            lib_path=str(config.lib_path), config=self._config
        )
        self._lock = threading.Lock()
        self._car = car

    @property
    def car(self) -> str:
        return self._car

    @property
    def context(self):
        return self._library.context

    @property
    def library(self) -> _ModuleLibrary:
        return self._library

    def init(self) -> None:
        """Initializes the library and sets the context.

        Error is raised if the library is not found or the context is not set.
        """
        self._library.init()

    def destroy(self) -> int:
        """Destroys the library and cleans up."""
        return self._library.destroy()  # type: ignore

    def device_initialized(self) -> bool:
        """Returns `True` if device is initialized, `False` otherwise."""
        return self._library.context is not None

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
        device.priority = (
            0  # Set priority to zero - the external server must ignore the priority.
        )
        device_identification = self._create_device_identification(device)
        return self._library.device_connected(device_identification)  # type: ignore

    def device_disconnected(
        self, disconnect_types: DisconnectTypes, device: _Device
    ) -> ReturnCode:
        """Handles device disconnection by creating the device identification and calling the library function.

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
            code = self._library.device_disconnected(
                disconnect_types, device_identification
            )
            self._check_device_disconnected_code(device.module, code, self._car)
            return code

    def _create_device_identification(self, device: _Device) -> DeviceIdentification:
        """Creates a DeviceIdentification structure based on the provided device object.

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
        role_length = device_id.device_role.size
        name_length = device_id.device_name.size
        if not device_id.device_role.data or role_length == 0:
            device.deviceRole = ""
        else:
            device.deviceRole = device_id.device_role.data[:role_length].decode("utf-8")

        if not device_id.device_name.data or name_length == 0:
            device.deviceName = ""
        else:
            device.deviceName = device_id.device_name.data[:name_length].decode("utf-8")
        return device

    def forward_status(self, status: _Status) -> ReturnCode:
        """
        Forwards a status update by creating the device identification and status buffer,
        and calling the library function.

        Parameters
        ----------
        device: Device
            The device object.

        statud: Status message.

        Returns
        -------
        int
            The result of the library function call.
        """
        device_identification = self._create_device_identification(
            status.deviceStatus.device
        )
        status_buffer = Buffer(
            data=status.deviceStatus.statusData,
            size=len(status.deviceStatus.statusData),
        )
        code = 0
        with self._lock:
            code = self._library.forward_status(status_buffer, device_identification)
            self._check_forward_status_code(status.deviceStatus.device, code, self._car)
        if status.errorMessage:
            self._log_status_error(status)
            self.forward_error_message(status.deviceStatus.device, status.errorMessage)
        return code

    def _log_status_error(self, status: _Status) -> None:
        """Log error if the status contains a non-empty error message."""
        if status.errorMessage:
            drepr = device_repr(status.deviceStatus.device)
            _logger.info(f"Status for {drepr} contains error.", self._car)

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
            code = 0
            code = self._library.forward_error_message(
                error_buffer, device_identification
            )
            self._check_forward_error_message_code(device.module, code, self._car)
            if code == _GeneralErrorCode.OK:
                _logger.debug(
                    f"Error message from {device_repr(device)} forwarded to API.", self._car
                )
            else:
                _logger.debug(
                    f"Error message from {device_repr(device)} not forwarded to API.", self._car
                )
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
        code = self._library.wait_for_command(timeout)
        if code == _GeneralErrorCode.OK:
            _logger.debug("Command received", self._car)
        return code  # type: ignore

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
        command_buffer = _empty_command_buffer()
        device_identification = _empty_device_identification()
        rc = self._library.pop_command(command_buffer, device_identification)
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
            code = self._library.command_ack(command_buffer, device_id)
            self._check_command_ack_code(device.module, code, self._car)
            return code

    def deallocate(self, buffer: Buffer) -> None:
        self._library.deallocate(buffer)

    def get_module_number(self) -> int:
        return self._library.get_module_number()

    def is_device_type_supported(self, device_type: int) -> bool:
        code = self._library.is_device_type_supported(device_type)
        return code == _GeneralErrorCode.OK

    @staticmethod
    def _check_forward_status_code(module_id: int, code: int, car: str) -> None:
        if code != _GeneralErrorCode.OK:
            _logger.error(
                f"Module {module_id}: Error in forward_status function, code: {code}", car
            )

    @staticmethod
    def _check_forward_error_message_code(module_id: int, code: int, car: str) -> None:
        if code != _GeneralErrorCode.OK:
            _logger.error(
                f"Module {module_id}: Error in forward_error_message function, code: {code}", car
            )

    @staticmethod
    def _check_device_disconnected_code(module_id: int, code: int, car: str) -> None:
        if code != _GeneralErrorCode.OK:
            _logger.error(
                f"Module {module_id}: Error in device_disconnected function, code: {code}", car
            )

    @staticmethod
    def _check_command_ack_code(module_id: int, code: int, car: str) -> None:
        if code != _GeneralErrorCode.OK:
            _logger.error(
                f"Module {module_id}: Error in command_ack function, code: {code}", car
            )
