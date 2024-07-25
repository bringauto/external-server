from __future__ import annotations
import dataclasses

from InternalProtocol_pb2 import Device as _Device  # type: ignore


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
            raise TypeError

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


@dataclasses.dataclass
class KnownDevices:
    """ This class manages two parallel lists of DevicePy instances representing
    devices communicating with the external server.
    """
    _supported: list[DevicePy] = dataclasses.field(default_factory=list)
    _unsupported: list[DevicePy] = dataclasses.field(default_factory=list)

    @property
    def n_supported(self) -> int:
        return len(self._supported)

    @property
    def n_unsupported(self) -> int:
        return len(self._unsupported)

    @property
    def n_all(self) -> int:
        return len(self._supported) + len(self._unsupported)

    def clear(self) -> None:
        self._supported.clear()
        self._unsupported.clear()

    def add_supported(self, device: DevicePy) -> None:
        """Add device to unsupported devices list.

        If device is already in supported devices list, no action is taken.
        If device is in unsupported devices list, it is removed from unsupported devices list.
        """
        if device in self._unsupported:
            self._unsupported.remove(device)
        self._supported.append(device)

    def list_supported(self) -> list[DevicePy]:
        """Return a copy of the supported devices list."""
        return self._supported.copy()

    def list_unsupported(self) -> list[DevicePy]:
        """Return a copy of the unsupported devices list."""
        return self._unsupported.copy()

    def add_unsupported(self, device: DevicePy) -> None:
        """Add device to not supported devices list.

        If device is already in unsupported devices list, no action is taken.
        If device is in supported devices list, it is removed from supported devices list.
        """
        if device in self._supported:
            self._supported.remove(device)
        self._unsupported.append(device)

    def is_supported(self, device: DevicePy) -> bool:
        return device in self._supported

    def any_supported_device(self, module_id: int) -> bool:
        return any(device.module_id == module_id for device in self._supported)

    def is_unsupported(self, device: DevicePy) -> bool:
        return device in self._unsupported

    def is_unknown(self, device: DevicePy) -> bool:
        """True if device is not in supported or unsupported devices list."""
        return not (self.is_supported(device) or self.is_unsupported(device))

    def remove(self, device: DevicePy) -> None:
        """Remove device from supported or unsupported devices list.

        If device is not in supported or unsupported devices list, no action is taken.
        """
        if device in self._supported:
            self._supported.remove(device)
        elif device in self._unsupported:
            self._unsupported.remove(device)
