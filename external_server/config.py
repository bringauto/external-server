from __future__ import annotations
import json
import os
import logging.config

from typing import Annotated, TypeVar, Mapping

from pydantic import (
    BaseModel,
    DirectoryPath,
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
    log_files_directory: DirectoryPath
    log_files_to_keep: int = Field(ge=0)
    log_file_max_size_bytes: int = Field(ge=0)
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
            log_files_directory=config.log_files_directory,
            log_files_to_keep=config.log_files_to_keep,
            log_file_max_size_bytes=config.log_file_max_size_bytes,
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
    log_files_directory: DirectoryPath
    log_files_to_keep: int = Field(ge=0)
    log_file_max_size_bytes: int = Field(ge=0)
    common_modules: dict[ModuleID, ModuleConfig]
    cars: dict[str, CarModulesConfig]

    @model_validator(mode="before")
    @classmethod
    def modules_validator(cls, fields: T) -> T:
        modules = fields.get("common_modules")
        cars = fields.get("cars")
        if not cars:
            raise InvalidConfiguration("Cars must contain at least 1 car.")
        elif not modules and not all(
            car.get("specific_modules") for car in cars.values()
        ):
            raise InvalidConfiguration(
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
                raise InvalidConfiguration(
                    "Each module can be configured either globally or per car, but not both. \n"
                    f"IDs of modules defined both globally and per car: {duplicates}."
                )

        return fields

    def get_config_dump_string(self) -> str:
        """Returns a string representation of the config. Values need to be added explicitly."""
        config_json: dict = {}
        config_json["company_name"] = self.company_name
        config_json["mqtt_address"] = self.mqtt_address
        config_json["mqtt_port"] = self.mqtt_port
        config_json["mqtt_timeout"] = self.mqtt_timeout
        config_json["timeout"] = self.timeout
        config_json["send_invalid_command"] = self.send_invalid_command
        config_json["sleep_duration_after_connection_refused"] = (
            self.sleep_duration_after_connection_refused
        )
        config_json["log_files_directory"] = str(self.log_files_directory)
        config_json["log_files_to_keep"] = self.log_files_to_keep
        config_json["log_file_max_size_bytes"] = self.log_file_max_size_bytes

        module_json = {}
        for key, value in self.common_modules.items():
            module_json[key] = {"lib_path": str(value.lib_path), "config": "HIDDEN"}
        config_json["common_modules"] = module_json

        car_json = {}
        for car_name in self.cars:
            module_json = {}
            for key, value in self.common_modules.items():
                if not key in config_json["common_modules"]:
                    module_json[key] = {
                        "lib_path": str(value.lib_path),
                        "config": "HIDDEN",
                    }
            car_json[car_name] = {"specific_modules": module_json}
        config_json["cars"] = car_json

        return json.dumps(config_json, indent=4)


class ModuleConfig(BaseModel):
    lib_path: FilePath
    config: dict[str, str]


def load_config(config_path: str) -> ServerConfig:
    try:
        with open(config_path) as config_file:
            data = config_file.read()
    except OSError as e:
        raise InvalidConfiguration(f"Config could not be loaded: {e}") from None

    try:
        config = ServerConfig.model_validate_json(data)
    except ValidationError as e:
        raise InvalidConfiguration(e) from None

    return config


def configure_logging(config_path: str) -> None:
    try:
        with open(config_path) as f:
            logging.config.dictConfig(json.load(f))
    except Exception:
        logger = logging.getLogger()
        logger.warning(
            f"External server: Could not find a logging configuration file (entered path: {config_path}. Using default logging configuration."
        )

        if not os.path.isfile("log/external_server.log"):
            if not os.path.exists("log"):
                os.makedirs("log")
            with open("log/external_server.log", "w") as f:
                f.write("")

        if not logger.hasHandlers():  # Prevents adding hanlders multiple times
            logger.propagate = False
            formatter = logging.Formatter(
                fmt="[%(asctime)s.%(msecs)03d] [external-server] [%(levelname)s]\t %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
            file_handler = logging.FileHandler("log/external_server.log")
            file_handler.setLevel(level=logging.INFO)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)

            stream_handler = logging.StreamHandler()
            stream_handler.setFormatter(formatter)
            stream_handler.setLevel(level=logging.INFO)
            logger.addHandler(stream_handler)

            logger.setLevel(level=logging.INFO)
            if not os.path.exists("log"):
                os.makedirs("log")
