from __future__ import annotations
from typing import Annotated, TypeVar, Mapping

from pydantic import (
    BaseModel,
    Field,
    FilePath,
    field_validator,
    model_validator,
    StringConstraints,
    ValidationError,
)


T = TypeVar("T", bound=Mapping)


_COMPANY_NAME_PATTERN = r"^[a-z0-9_]*$"
_CAR_NAME_PATTERN = r"^[a-z0-9_]*$"
_MQTT_ADDRESS_PATTERN = r"^((http|https)://)?([\w-]+\.)?+[\w-]+$"
_MODULE_ID_PATTERN = r"^\d+$"


class InvalidConfiguration(Exception):
    pass


class CarModulesConfig(BaseModel):
    specific_modules: dict[
        Annotated[str, StringConstraints(pattern=_MODULE_ID_PATTERN)], ModuleConfig
    ] = {}


CompanyName = Annotated[str, StringConstraints(pattern=_COMPANY_NAME_PATTERN)]
CarName = Annotated[str, StringConstraints(pattern=_CAR_NAME_PATTERN)]
MQTTAdress = Annotated[str, StringConstraints(pattern=_MQTT_ADDRESS_PATTERN)]
ModuleID = Annotated[str, StringConstraints(pattern=_MODULE_ID_PATTERN)]


class CarConfig(BaseModel):
    company_name: CompanyName
    car_name: CarName
    mqtt_address: MQTTAdress
    mqtt_port: int = Field(ge=0, le=65535)
    mqtt_timeout: float = Field(ge=0)
    timeout: float = Field(ge=0)
    send_invalid_command: bool
    sleep_duration_after_connection_refused: float = Field(ge=0)
    modules: dict[ModuleID, ModuleConfig]

    @staticmethod
    def from_server_config(car_name: str, config: ServerConfig) -> CarConfig:
        modules = config.cars[car_name].specific_modules.copy()
        modules.update(config.common_modules)
        return CarConfig(
            company_name=config.company_name,
            car_name=car_name,
            mqtt_address=config.mqtt_address,
            mqtt_port=config.mqtt_port,
            mqtt_timeout=config.mqtt_timeout,
            timeout=config.timeout,
            send_invalid_command=config.send_invalid_command,
            sleep_duration_after_connection_refused=config.sleep_duration_after_connection_refused,
            modules=modules,
        )

    @field_validator("modules")
    @classmethod
    def modules_validator(
        cls, modules: dict[ModuleID, ModuleConfig]
    ) -> dict[ModuleID, ModuleConfig]:
        if not modules:
            raise ValueError("Modules must contain at least 1 module.")
        return modules


class ServerConfig(BaseModel):
    company_name: CompanyName
    mqtt_address: MQTTAdress
    mqtt_port: int = Field(ge=0, le=65535)
    mqtt_timeout: float = Field(ge=0)
    timeout: float = Field(ge=0)
    send_invalid_command: bool
    sleep_duration_after_connection_refused: float = Field(ge=0)
    common_modules: dict[ModuleID, ModuleConfig]
    cars: dict[str, CarModulesConfig]

    @model_validator(mode="before")
    @classmethod
    def modules_validator(cls, fields: T) -> T:
        modules = fields.get("common_modules")
        cars: dict[str, dict] = fields.get("cars", {})
        if not cars:
            raise ValueError("Cars must contain at least 1 car.")
        elif not modules and not all(
            car.get("specific_modules", {}) for car in cars.values()
        ):
            raise ValueError(
                "Modules must contain at least 1 module for each car."
            )
        elif modules:
            car_specific_modules = set.union(
                *[set(car.get("specific_modules", {}).keys()) for car in cars.values()]
            )
            global_modules = set(modules.keys())
            duplicates = [
                int(i) for i in car_specific_modules.intersection(global_modules)
            ]
            if duplicates:
                raise ValueError(
                    "Each module can be configured either globally or per car, but not both. \n"
                    f"IDs of modules defined both globally and per car: {duplicates}."
                )

        return fields


class ModuleConfig(BaseModel):
    lib_path: FilePath
    config: dict[str, str | int] = Field(exclude=True)


def load_config(config_path: str) -> ServerConfig:
    try:
        with open(config_path) as config_file:
            data = config_file.read()
    except OSError as e:
        raise InvalidConfiguration(f"Config could not be loaded. {e}") from None

    try:
        config = ServerConfig.model_validate_json(data)
    except ValidationError as e:
        raise InvalidConfiguration(e) from None

    return config


