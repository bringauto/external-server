from fleet_protocol_protobuf_files.InternalProtocol_pb2 import (
    Device as _Device,
)
from fleet_protocol_protobuf_files.ExternalProtocol_pb2 import (
    Status as _Status
)
from external_server.models.structures import (
    Buffer,
    DeviceIdentification,
    DisconnectTypes,
    GeneralErrorCode as _GeneralErrorCode,
    EsErrorCode as _EsErrorCode,
)
from external_server.models.devices import device_repr
from external_server.config import ModuleConfig
from external_server.adapters.api.module_lib import (
    empty_command_buffer as _empty_command_buffer,
    empty_device_identification as _empty_device_identification,
    ModuleLibrary as _ModuleLibrary,
)
from external_server.logs import CarLogger as _CarLogger


_logger = _CarLogger()


class APIClientAdapter:
    """The class provides access to the module's API by providing connection with module's .so libraries
    using the ModuleLibrary class.
    """

    def __init__(self, config: ModuleConfig, company: str, car: str) -> None:
        """Initializes API Wrapper for Module.

        - `config` - JSON config for specific module
        - `company` - company name, which will be forwarded as first key-value to API
        - `car` - car name, which will be forwarded as second key-value to API
        """
        self._lib_path = config.lib_path.absolute().as_posix()
        self._config: dict[str, str | int] = {"company_name": company, "car_name": car}
        self._config.update(config.config)
        self._library = _ModuleLibrary(lib_path=str(config.lib_path), config=self._config)
        self._car = car

    @property
    def car(self) -> str:
        return self._car

    @property
    def company(self) -> str:
        return str(self._config.get("company_name", ""))

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
        if self._library.context is None:
            raise RuntimeError("Failed to initialize library: context not set")

    def destroy(self) -> int:
        """Destroys the library and cleans up."""
        return self._library.destroy()  # type: ignore

    def device_initialized(self) -> bool:
        """Returns `True` if device is initialized, `False` otherwise."""
        return self._library.context is not None

    def _invalid_identification_msg(self, device: _Device) -> str:
        """Returns a message indicating that the device identification is invalid."""
        device_str = device.SerializeToString().replace("\n", ", ")
        return (
            f"Module {device.module}: Device {device_str} has invalid identification."
            "Check the role (must be utf-8 encodable nonempty string) and name (must be utf-8 encodable nonempty string)."
        )

    def device_connected(self, device: _Device) -> int:
        """Handles device connection by creating the device identification and calling
        the library function.

        Parameters
        ----------
        `device` - The device object.

        Returns
        -------
        int
            The result of the library function call.
        """
        device.priority = 0  # Set priority to zero - the external server must ignore the priority.
        device_identification = DeviceIdentification.from_device(device)
        if not device_identification.is_valid():
            _logger.warning(
                self._invalid_identification_msg(device) + " Cannot connect.", self._car
            )
            return _GeneralErrorCode.NOT_OK
        return self._library.device_connected(device_identification)  # type: ignore

    def device_disconnected(self, disconnect_types: DisconnectTypes, device: _Device) -> int:
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
        device_identification = DeviceIdentification.from_device(device)
        if not device_identification.is_valid():
            _logger.warning(
                self._invalid_identification_msg(device) + " Cannot disconnect.", self._car
            )
            return _GeneralErrorCode.NOT_OK
        code = self._library.device_disconnected(disconnect_types, device_identification)
        if code != _GeneralErrorCode.OK:
            self.log_nok_device_disconnect(device, code, self._car)
        return code

    def _create_protobuf_device(self, device_id: DeviceIdentification) -> _Device:
        device = _Device()
        device.module = device_id.module
        device.priority = device_id.priority
        device.deviceType = device_id.device_type
        device.deviceRole = (
            device_id.device_role.data[: device_id.device_role.size].decode("utf-8") if (
                device_id.device_role.data and device_id.device_role.size > 0 ) else ""
        )
        device.deviceName = (
            device_id.device_name.data[: device_id.device_name.size].decode("utf-8") if (
                device_id.device_name.data and device_id.device_name.size > 0) else ""
        )
        return device

    def forward_status(self, status: _Status) -> int:
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
        device_identification = DeviceIdentification.from_device(status.deviceStatus.device)
        if not device_identification.is_valid():
            _logger.warning(
                self._invalid_identification_msg(status.deviceStatus.device)
                + " Cannot forward status.",
                self._car,
            )
            return _GeneralErrorCode.NOT_OK
        drepr = device_repr(status.deviceStatus.device)
        data = status.deviceStatus.statusData
        status_buffer = Buffer(data=data, size=len(data))
        code = self._library.forward_status(status_buffer, device_identification)
        if code == _GeneralErrorCode.OK:
            _logger.debug(f"Status for the device {drepr} forwarded to API", self._car)
        else:
            self._log_nok_forward_status(status.deviceStatus.device, code, self._car)
        if status.errorMessage:
            _logger.info(f"Status for {drepr} contains error message.", self._car)
            self.forward_error_message(status.deviceStatus.device, status.errorMessage)
        return code

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
        device_identification = DeviceIdentification.from_device(device)
        if not device_identification.is_valid():
            _logger.warning(
                self._invalid_identification_msg(device) + " Cannot forward error message.",
                self._car,
            )
            return _GeneralErrorCode.NOT_OK
        error_buffer = Buffer(data=error_bytes, size=len(error_bytes))
        code = self._library.forward_error_message(error_buffer, device_identification)
        if code == _GeneralErrorCode.OK:
            _logger.debug(f"Error message from {device_repr(device)} forwarded to API.", self._car)
        else:
            self._log_nok_forward_error(device.module, code, self._car)
        return code

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
        code = self._library.wait_for_command(timeout)
        if code == _GeneralErrorCode.OK:
            _logger.debug("Command received", self._car)
        return code  # type: ignore

    def pop_command(self) -> tuple[bytes, _Device, int]:
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
        try:
            rc = self._library.pop_command(command_buffer, device_identification)
            device = self._create_protobuf_device(device_identification)
            command_bytes = (
                bytes(command_buffer.data[: command_buffer.size])
                if command_buffer and command_buffer.data
                else b""
            )
            return command_bytes, device, rc
        finally:
            self.deallocate(device_identification.device_role)
            self.deallocate(device_identification.device_name)
            self.deallocate(command_buffer)

    def command_ack(self, command_data: bytes, device: _Device) -> int:
        """Calls command_ack function from API."""
        device_id = DeviceIdentification.from_device(device)
        if not device_id.is_valid():
            _logger.warning(
                self._invalid_identification_msg(device) + " Cannot acknowledge command.",
                self._car,
                stack_level_up=1,
            )
        command_buffer = Buffer(command_data, len(command_data))
        code = self._library.command_ack(command_buffer, device_id)
        if code != _GeneralErrorCode.OK:
            self._log_nok_command_ack(device.module, code, self._car)
        return code

    def deallocate(self, buffer: Buffer) -> None:
        self._library.deallocate(buffer)

    def get_module_number(self) -> int:
        return self._library.get_module_number()

    def is_device_type_supported(self, device_type: int) -> bool:
        code = self._library.is_device_type_supported(device_type)
        return code == _GeneralErrorCode.OK

    @staticmethod
    def _log_nok_forward_status(module_id: int, code: int, car: str) -> None:
        _logger.error(
            f"Module {module_id}: Error in forward_status function, code: {code}.",
            car,
            stack_level_up=1,
        )

    @staticmethod
    def _log_nok_forward_error(module_id: int, code: int, car: str) -> None:
        _logger.error(
            f"Module {module_id}: Error in forward_error_message function, code: {code}.",
            car,
            stack_level_up=1,
        )

    @staticmethod
    def log_nok_device_disconnect(device_id: _Device, code: int, car: str) -> None:
        if code == _GeneralErrorCode.NOT_OK:
            _logger.warning(
                f"Module {device_id.module}: Device {device_id} not not among conected devices, code: {code}.",
                car,
                stack_level_up=1,
            )
        elif code == _EsErrorCode.CONTEXT_INCORRECT:
            _logger.error(f"Module {device_id.module}: Context incorrect, code: {code}.", car, 1)
        else:
            _logger.error(
                f"Module {device_id.module}: Error in device_disconnected function, code: {code}.",
                car,
                stack_level_up=1,
            )

    @staticmethod
    def _log_nok_command_ack(module_id: int, code: int, car: str) -> None:
        _logger.error(
            f"Module {module_id}: Error in command_ack function, code: {code}.",
            car,
            stack_level_up=1,
        )
