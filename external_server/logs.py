from typing import Optional, Type
import abc
import logging

from external_server.models.exceptions import (  # type: ignore
    ConnectSequenceFailure,
    CommunicationException,
    StatusTimeout,
    NoPublishedMessage,
    CommandResponseTimeout,
    SessionTimeout,
    UnexpectedMQTTDisconnect,
)


class _Logger(abc.ABC):

    def __init__(self, logger_name: Optional[str] = None) -> None:
        self._logger = logging.getLogger(logger_name)

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


LOG_LEVELS: dict[Type[Exception], int] = {
    ConnectSequenceFailure: logging.WARNING,
    NoPublishedMessage: logging.WARNING,
    CommandResponseTimeout: logging.WARNING,
    SessionTimeout: logging.WARNING,
    StatusTimeout: logging.WARNING,
    UnexpectedMQTTDisconnect: logging.WARNING,
}
