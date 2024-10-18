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


LOGGER_NAME = "external_server"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_log_level_by_verbosity = {False: logging.WARNING, True: logging.DEBUG}


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


def configure_logging(component_name: str, config: dict) -> None:
    """Configure the logging for the application.

    The component name is written in the log messages to identify the source of the log message.

    The logging configuration is read from a JSON file. If the file is not found, a default configuration is used.
    """

    log_config = config["logging"]
    logger = logging.getLogger(LOGGER_NAME)
    try:
        verbose: bool = log_config["verbose"]
        logger.setLevel(_log_level_by_verbosity[verbose])
    except KeyError as e:
        logging.error(f"{component_name}: Missing logging configuration. {e}")
    except Exception as e:
        logging.error(f"{component_name}: Could not configure logging. {e}")

    try:
        # create formatter
        formatter = logging.Formatter(_log_format(component_name), datefmt=_DATE_FORMAT)
        # console handler
        if verbose:
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(formatter)
            logger.addHandler(console_handler)
        # file handler
        file_path = os.path.join(log_config["log-path"], _log_file_name(component_name) + ".log")
        file_handler = logging.handlers.RotatingFileHandler(
            file_path, maxBytes=10485760, backupCount=5
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except KeyError as e:
        logging.error(f"{component_name}: Missing logging configuration. {e}")
    except Exception as e:
        logging.error(f"{component_name}: Could not configure logging. {e}")


def _log_format(component_name: str) -> str:
    log_component_name = "-".join(component_name.lower().split())
    return f"[%(asctime)s.%(msecs)03d]\t[{log_component_name}]\t[%(levelname)s]\t%(message)s"


def _log_file_name(component_name: str) -> str:
    return "_".join(component_name.lower().split())
