from __future__ import annotations

from typing import Annotated, TypeVar, Mapping

from pydantic import BaseModel, Field, FilePath, StringConstraints, ValidationError, field_validator, DirectoryPath

T = TypeVar("T", bound=Mapping)


class Config(BaseModel):
    company_name: Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]*$")]
    car_name: Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]*$")]
    mqtt_address: Annotated[str, StringConstraints(pattern=r"^((http|https)://)?([\w-]+\.)?+[\w-]+$")]
    mqtt_port: int = Field(ge=0, le=65535)
    mqtt_timeout: int = Field(ge=0)
    timeout: int = Field(ge=0)
    send_invalid_command: bool
    sleep_duration_after_connection_refused: float = Field(ge=0)
    log_files_directory: DirectoryPath
    log_files_to_keep: int = Field(ge=0)
    log_file_max_size_bytes: int = Field(ge=0)
    modules: dict[Annotated[str, StringConstraints(pattern=r"^\d+$")], ModuleConfig]

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
