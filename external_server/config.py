from __future__ import annotations
import json
import logging.config

from typing import Annotated, TypeVar, Mapping

from pydantic import (
    BaseModel,
    DirectoryPath,
    field_validator,
    Field,
    FilePath,
    StringConstraints,
    ValidationError,
)


T = TypeVar("T", bound=Mapping)


_COMPANY_NAME_PATTERN = r"^[a-z0-9_]*$"
_CAR_NAME_PATTERN = r"^[a-z0-9_]*$"
_MQTT_ADDRESS_PATTERN = r"^((http|https)://)?([\w-]+\.)?+[\w-]+$"
_MODULE_ID_PATTERN = r"^\d+$"


class Config(BaseModel):
    company_name: Annotated[str, StringConstraints(pattern=_COMPANY_NAME_PATTERN)]
    car_name: Annotated[str, StringConstraints(pattern=_CAR_NAME_PATTERN)]
    mqtt_address: Annotated[str, StringConstraints(pattern=_MQTT_ADDRESS_PATTERN)]
    mqtt_port: int = Field(ge=0, le=65535)
    mqtt_timeout: float = Field(ge=0)
    timeout: float = Field(ge=0)
    send_invalid_command: bool
    sleep_duration_after_connection_refused: float = Field(ge=0)
    log_files_directory: DirectoryPath
    log_files_to_keep: int = Field(ge=0)
    log_file_max_size_bytes: int = Field(ge=0)
    modules: dict[Annotated[str, StringConstraints(pattern=_MODULE_ID_PATTERN)], ModuleConfig]

    @field_validator("modules")
    @classmethod
    def _modules_validator(cls, modules: T) -> T:
        if not len(modules):
            raise ValueError("Modules must contain at least 1 module.")
        for module in modules.values():
            if module.config.get("company_name") is not None:
                raise ValueError("Module configs can not contain company_name.")
            if module.config.get("car_name") is not None:
                raise ValueError("Module configs can not contain car_name.")
        return modules

    def get_config_dump_string(self) -> str:
        """Returns a string representation of the config. Values need to be added explicitly."""
        config_json: dict = {}
        config_json["company_name"] = self.company_name
        config_json["car_name"] = self.car_name
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
        for key, value in self.modules.items():
            module_json[key] = {"lib_path": str(value.lib_path), "config": "HIDDEN"}
        config_json["modules"] = module_json

        return json.dumps(config_json, indent=4)


class ModuleConfig(BaseModel):
    lib_path: FilePath
    config: dict[str, str]


class InvalidConfigError(Exception):
    pass


def load_config(config_path: str) -> Config:
    try:
        with open(config_path) as config_file:
            data = config_file.read()
    except OSError as e:
        raise InvalidConfigError(f"Config could not be loaded: {e}") from None

    try:
        config = Config.model_validate_json(data)
    except ValidationError as e:
        raise InvalidConfigError(e) from None

    return config


def configure_logging(config_path: str) -> None:
    try:
        with open(config_path) as f:
            logging.config.dictConfig(json.load(f))
    except Exception:
        logging.warning(
            f"External server: Could not find a logging configuration file (entered path: {config_path}. Using default logging configuration."
        )
        logging.basicConfig(level=logging.INFO)
        logging.getLogger().addHandler(logging.FileHandler("log/external_server.log"))
