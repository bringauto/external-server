from typing import Type, Any
import abc
import logging.handlers
import os

from external_server.models.exceptions import (  # type: ignore
    CommunicationException,
    ConnectSequenceFailure,
    StatusTimeout,
    NoMessage,
    CommandResponseTimeout,
    SessionTimeout,
    UnexpectedMQTTDisconnect,
)
from external_server.config import LoggingConfig as _Config


LOGGER_NAME = "external_server"
PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
LOG_LEVELS: dict[Type[Exception], int] = {
    CommunicationException: logging.WARNING,
    ConnectSequenceFailure: logging.WARNING,
    NoMessage: logging.INFO,
    CommandResponseTimeout: logging.INFO,
    SessionTimeout: logging.INFO,
    StatusTimeout: logging.INFO,
    UnexpectedMQTTDisconnect: logging.WARNING,
}


class _Logger(abc.ABC):
    """Abstract class for wrapping a logger from the Python logging module."""

    def __init__(self, logger_name: str = LOGGER_NAME) -> None:
        self._logger = logging.getLogger(logger_name)
        self._logger.setLevel(logging.INFO)

    @property
    def logger(self) -> logging.Logger:
        return self._logger

    @abc.abstractmethod
    def debug(self, msg: str, car_name: str, stack_level_up: int = 0) -> None:
        pass

    @abc.abstractmethod
    def info(self, msg: str, car_name: str, stack_level_up: int = 0) -> None:
        pass

    @abc.abstractmethod
    def warning(self, msg: str, car_name: str, stack_level_up: int = 0) -> None:
        pass

    @abc.abstractmethod
    def error(self, msg: str, car_name: str, stack_level_up: int = 0) -> None:
        pass

    @abc.abstractmethod
    def log_on_exception(self, e: Exception, car_name: str, stack_level_up: int = 0) -> None:
        pass

    def format_caller_info(self, caller_info: tuple[str, int, str, Any]) -> str:
        module_path, line, _, _ = caller_info
        module_path = os.path.relpath(module_path, PROJECT_ROOT)
        return f"[{module_path}:{line}]"


class CarLogger(_Logger):
    """Logger class for logging messages, forcing including the car name in the log message.

    The car name is necessary to identify the source of the log message.
    """

    def debug(self, msg: str, car_name: str, stack_level_up: int = 0) -> None:
        self._logger.debug(
            self._msg(car_name, msg, self._logger.findCaller(stacklevel=2 + stack_level_up))
        )

    def info(self, msg: str, car_name: str, stack_level_up: int = 0) -> None:
        self._logger.info(
            self._msg(car_name, msg, self._logger.findCaller(stacklevel=2 + stack_level_up))
        )

    def warning(self, msg: str, car_name: str, stack_level_up: int = 0) -> None:
        self._logger.warning(
            self._msg(car_name, msg, self._logger.findCaller(stacklevel=2 + stack_level_up))
        )

    def error(self, msg: str, car_name: str, stack_level_up: int = 0) -> None:
        self._logger.error(
            self._msg(car_name, msg, self._logger.findCaller(stacklevel=2 + stack_level_up))
        )

    def log_on_exception(self, e: Exception, car_name: str, stack_level_up: int = 0) -> None:
        log_level = LOG_LEVELS.get(type(e), logging.ERROR)
        self._logger.log(
            log_level,
            self._msg(car_name, str(e), self._logger.findCaller(stacklevel=2 + stack_level_up)),
        )

    def _msg(self, car_name: str, msg: str, caller_info: tuple[str, int, str, Any]) -> str:
        car_name = car_name.strip()
        if car_name:
            return f"{self.format_caller_info(caller_info)}\t({car_name})\t{msg}"
        else:
            return f"{self.format_caller_info(caller_info)}\t(undefined car)\t{msg}"


class ESLogger(_Logger):
    """Logger class for logging messages at the level of the whole external server, outside of any car's context."""

    def debug(self, msg: str, *args, stack_level_up: int = 0) -> None:
        self._logger.debug(self._msg(msg, self._logger.findCaller(stacklevel=2 + stack_level_up)))

    def info(self, msg: str, *args, stack_level_up: int = 0) -> None:
        self._logger.info(self._msg(msg, self._logger.findCaller(stacklevel=2 + stack_level_up)))

    def warning(self, msg: str, *args, stack_level_up: int = 0) -> None:
        self._logger.warning(self._msg(msg, self._logger.findCaller(stacklevel=2 + stack_level_up)))

    def error(self, msg: str, *args, stack_level_up: int = 0) -> None:
        self._logger.error(self._msg(msg, self._logger.findCaller(stacklevel=2 + stack_level_up)))

    def log_on_exception(self, e: Exception, *args, stack_level_up: int = 0) -> None:
        log_level = LOG_LEVELS.get(type(e), logging.ERROR)
        self._logger.log(
            log_level, self._msg(str(e), self._logger.findCaller(stacklevel=2 + stack_level_up))
        )

    def _msg(self, msg: str, caller_info: tuple[str, int, str, Any]) -> str:
        return f"{self.format_caller_info(caller_info)} (server)\t{msg}"


def configure_logging(component_name: str, config: _Config) -> None:
    """Configure the logging for the application.

    The component name is written in the log messages to identify the source of the log message.

    The logging configuration is read from a JSON file. If the file is not found, a default configuration is used.
    """
    try:
        if config.console.use:
            _configure_logging_to_console(config.console, component_name)
        if config.file.use:
            _configure_logging_to_file(config.file, component_name)
        logging.getLogger(LOGGER_NAME).setLevel(
            logging.DEBUG
        )  # This ensures the logging level will be fully determined by the handlers
    except ValueError as ve:
        logging.error(f"{component_name}: Configuration error: {ve}")
        raise
    except Exception as e:
        logging.error(f"{component_name}: Error when configuring logging: {e}")
        raise


def _configure_logging_to_console(config: _Config.HandlerConfig, component_name: str):
    """Configure the logging to the console.

    The console logging is configured to use the logging level and format specified in the configuration.
    """
    handler = logging.StreamHandler()
    handler.setLevel(config.level)
    _add_formatter(handler, component_name)
    _use_handler(handler)


def _configure_logging_to_file(config: _Config.HandlerConfig, component_name: str) -> None:
    """Configure the logging to a file.

    The file logging is configured to use the logging level and format specified in the configuration.
    """
    if not config.path:
        raise ValueError(f"Log directory does not exist: {config.path}. Check the config file.")
    file_path = os.path.join(config.path, _log_file_name(component_name) + ".log")
    handler = logging.handlers.RotatingFileHandler(file_path, maxBytes=10485760, backupCount=5)
    handler.setLevel(config.level)
    _add_formatter(handler, component_name)
    _use_handler(handler)


def _add_formatter(handler: logging.Handler, component_name: str) -> None:
    """Set the formatter for the logging handler."""
    formatter = logging.Formatter(_log_format(component_name), datefmt=_DATE_FORMAT)
    handler.setFormatter(formatter)


def _use_handler(handler: logging.Handler) -> None:
    """Add handler to the logger."""
    logging.getLogger(LOGGER_NAME).addHandler(handler)


def _log_format(component_name: str) -> str:
    log_component_name = "-".join(component_name.lower().split())
    return f"[%(asctime)s.%(msecs)03d] [{log_component_name}] [%(levelname)s]\t %(message)s"


def _log_file_name(component_name: str) -> str:
    return "_".join(component_name.lower().split())
