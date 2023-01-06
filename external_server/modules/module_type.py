from enum import Enum, EnumMeta


class EnumHasValue(Enum):
    @classmethod
    def has_value(cls: EnumMeta, value: int) -> bool:
        return value in cls._value2member_map_


class ModuleType(EnumHasValue):
    RESERVED_MODULE = 0
    MISSION_MODULE = 1
    CAR_ACCESSORY_MODULE = 2
