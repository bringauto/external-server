from __future__ import annotations

from typing import Annotated, TypeVar, Mapping

from pydantic import BaseModel, FilePath, StringConstraints, ValidationError, field_validator

T = TypeVar("T", bound=Mapping)


class Config(BaseModel):
    company_name: str
    car_name: str
    mqtt_timeout: int
    timeout: int
    send_invalid_command: bool
    sleep_duration_after_connection_refused: float
    modules: dict[Annotated[str, StringConstraints(pattern=r"^\d+$")], ModuleConfig]

    @field_validator("modules")
    @classmethod
    def _modules_validator(cls, value: T) -> T:
        if not len(value):
            raise ValueError("Modules must contain at least 1 module.")
        return value


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
