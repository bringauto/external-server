from __future__ import annotations
import dataclasses

from InternalProtocol_pb2 import Device as _Device  # type: ignore
from InternalProtocol_pb2 import DeviceStatus as DeviceStatus  # type: ignore


def device_status(device: _Device, status_data: bytes = b"") -> DeviceStatus:
    return DeviceStatus(device=device, statusData=status_data)


@dataclasses.dataclass(frozen=True)
class DevicePy:
    """This class represents a device connected to the external server.

    It contains the device identifiers and methods for assessing two devices are identical.
    """

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
            return False

    def to_device(self) -> _Device:
        """Converts the DevicePy instance to the protobuf Device message."""
        return _Device(
            module=self.module_id,
            deviceType=self.type,
            deviceRole=self.role,
            deviceName=self.name,
            priority=self.priority,
        )

    @staticmethod
    def from_device(device: _Device) -> DevicePy:
        """Creates a DevicePy instance from the protobuf Device message."""
        return DevicePy(
            module_id=device.module,
            type=device.deviceType,
            role=device.deviceRole,
            name=device.deviceName,
            priority=device.priority,
        )


@dataclasses.dataclass
class KnownDevices:
    """This class manages two parallel lists of DevicePy instances representing
    devices communicating with the External Server.

    -   Device is *connected* if it was included in connect message or a status message
        with device status CONNECTING and has not yet become *not connected*.
    -   Device is *not connected* if it sent a status message with device status DISCONNECTED.
    """

    _connected: list[DevicePy] = dataclasses.field(default_factory=list)
    _not_connected: list[DevicePy] = dataclasses.field(default_factory=list)

    @property
    def n_connected(self) -> int:
        """Number of devices in connected devices list."""
        return len(self._connected)

    @property
    def n_not_connected(self) -> int:
        """Number of devices in not connected devices list."""
        return len(self._not_connected)

    @property
    def n_all(self) -> int:
        """Total number of devices in both connected and not connected devices lists."""
        return len(self._connected) + len(self._not_connected)

    def clear(self) -> None:
        """Clear both connected and not connected devices lists."""
        self._connected.clear()
        self._not_connected.clear()

    def connected(self, device: DevicePy) -> None:
        """Add device to connected devices list.

        If device is already in connected devices list, no action is taken.
        If device is in not connected devices list, it is removed from not connected devices list.
        """
        if device in self._not_connected:
            self._not_connected.remove(device)
        self._connected.append(device)

    def list_connected(self) -> list[DevicePy]:
        """Return a copy of the connected devices list."""
        return self._connected.copy()

    def list_not_connected(self) -> list[DevicePy]:
        """Return a copy of the not connected devices list."""
        return self._not_connected.copy()

    def not_connected(self, device: DevicePy) -> None:
        """Add device to not connected devices list.

        If device is already in not connected devices list, no action is taken.
        If device is in connected devices list, it is removed from connected devices list.
        """
        if device in self._connected:
            self._connected.remove(device)
        self._not_connected.append(device)

    def is_connected(self, device: DevicePy) -> bool:
        """`True` if device is in connected devices list, `False` otherwise."""
        return device in self._connected

    def any_connected_device(self, module_id: int) -> bool:
        """`True` if any device with given module ID is in connected devices list, `False` otherwise."""
        return any(device.module_id == module_id for device in self._connected)

    def is_not_connected(self, device: DevicePy) -> bool:
        """`True` if device is in not connected devices list, `False` otherwise."""
        return device in self._not_connected

    def is_known(self, device: DevicePy) -> bool:
        """True if device is in connected or not connected devices list."""
        return self.is_connected(device) or self.is_not_connected(device)

    def is_unknown(self, device: DevicePy) -> bool:
        """True if device is neither in connected and not connected devices list."""
        return not (self.is_connected(device) or self.is_not_connected(device))

    def remove(self, device: DevicePy) -> None:
        """Remove device from connected or not connected devices list.

        If device is not in connected or not connected devices list, no action is taken.
        """
        if device in self._connected:
            self._connected.remove(device)
        elif device in self._not_connected:
            self._not_connected.remove(device)


def device_repr(device: _Device | DevicePy) -> str:
    if isinstance(device, DevicePy):
        return f"{device.module_id}/{device.type}/{device.role}/{device.name}"
    else:
        return f"{device.module}/{device.deviceType}/{device.deviceRole}/{device.deviceName}"
