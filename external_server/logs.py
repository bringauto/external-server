from typing import Type
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
from external_server.config import ServerConfig as _Config, Logging as _Logging


LOGGER_NAME = "external_server"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class _Logger(abc.ABC):
    """Abstract class for wrapping a logger from the Python logging module."""

    def __init__(self, logger_name: str = LOGGER_NAME) -> None:
        self._logger = logging.getLogger(logger_name)
        self._logger.setLevel(logging.INFO)

    @abc.abstractmethod
    def debug(self, msg: str, car_name: str) -> None:
        pass

    @abc.abstractmethod
    def info(self, msg: str, car_name: str) -> None:
        pass

    @abc.abstractmethod
    def warning(self, msg: str, car_name: str) -> None:
        pass

    @abc.abstractmethod
    def error(self, msg: str, car_name: str) -> None:
        pass

    @abc.abstractmethod
    def log_on_exception(self, e: Exception, car_name: str) -> None:
        pass


class CarLogger(_Logger):
    """Logger class for logging messages, forcing including the car name in the log message.

    The car name is necessary to identify the source of the log message.
    """

    def debug(self, msg: str, car_name: str) -> None:
        self._logger.debug(self._car_msg(car_name, msg))

    def info(self, msg: str, car_name: str) -> None:
        self._logger.info(self._car_msg(car_name, msg))

    def warning(self, msg: str, car_name: str) -> None:
        self._logger.warning(self._car_msg(car_name, msg))

    def error(self, msg: str, car_name: str) -> None:
        self._logger.error(self._car_msg(car_name, msg))

    def log_on_exception(self, e: Exception, car_name: str) -> None:
        log_level = LOG_LEVELS.get(type(e), logging.ERROR)
        self._logger.log(log_level, self._car_msg(car_name, str(e)))

    @staticmethod
    def _car_msg(car_name: str, msg: str) -> str:
        car_name = car_name.strip()
        if car_name:
            return f"({car_name})\t {msg}"
        else:
            return msg


class ESLogger(_Logger):
    """Logger class for logging messages at the level of the whole external server, outside of any car's context."""

    def debug(self, msg: str, *args) -> None:
        self._logger.debug(self._msg(msg))

    def info(self, msg: str, *args) -> None:
        self._logger.info(self._msg(msg))

    def warning(self, msg: str, *args) -> None:
        self._logger.warning(self._msg(msg))

    def error(self, msg: str, *args) -> None:
        self._logger.error(self._msg(msg))

    def log_on_exception(self, e: Exception, *args) -> None:
        log_level = LOG_LEVELS.get(type(e), logging.ERROR)
        self._logger.log(log_level, self._msg(str(e)))

    def _msg(self, msg: str) -> str:
        return f"(server)\t {msg}"


DEFAULT_EXCEPTION_LOG_LEVEL = logging.WARNING

LOG_LEVELS: dict[Type[Exception], int] = {
    CommunicationException: DEFAULT_EXCEPTION_LOG_LEVEL,
    ConnectSequenceFailure: DEFAULT_EXCEPTION_LOG_LEVEL,
    NoMessage: DEFAULT_EXCEPTION_LOG_LEVEL,
    CommandResponseTimeout: DEFAULT_EXCEPTION_LOG_LEVEL,
    SessionTimeout: DEFAULT_EXCEPTION_LOG_LEVEL,
    StatusTimeout: DEFAULT_EXCEPTION_LOG_LEVEL,
    UnexpectedMQTTDisconnect: DEFAULT_EXCEPTION_LOG_LEVEL,
}


def configure_logging(component_name: str, config: _Config) -> None:
    """Configure the logging for the application.

    The component name is written in the log messages to identify the source of the log message.

    The logging configuration is read from a JSON file. If the file is not found, a default configuration is used.
    """
    try:
        log_config = config.logging

        if log_config.console.use:
            _configure_logging_to_console(log_config.console, component_name)
        if log_config.file.use:
            _configure_logging_to_file(log_config.file, component_name)
        logging.getLogger(LOGGER_NAME).setLevel(
            logging.DEBUG
        )  # This ensures the logging level will be fully determined by the handlers
    except ValueError as ve:
        logging.error(f"{component_name}: Configuration error: {ve}")
        raise
    except Exception as e:
        logging.error(f"{component_name}: Error when configuring logging: {e}")
        raise


def _configure_logging_to_console(config: _Logging.HandlerConfig, component_name: str):
    """Configure the logging to the console.

    The console logging is configured to use the logging level and format specified in the configuration.
    """
    handler = logging.StreamHandler()
    handler.setLevel(config.level)
    _add_formatter(handler, component_name)
    _use_handler(handler)


def _configure_logging_to_file(config: _Logging.HandlerConfig, component_name: str) -> None:
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
