from enum import Enum
import logging

from pydantic import BaseModel, ValidationError
from pydantic.dataclasses import dataclass

from external_server.modules.message_creator import MessageCreator
import external_server.protobuf.ExternalProtocol_pb2 as external_protocol
import external_server.protobuf.InternalProtocol_pb2 as internal_protocol


@dataclass
class Position:
    latitude: float
    longitude: float
    altitude: float


@dataclass
class Station:
    name: str
    position: Position


class Telemetry(BaseModel):
    speed: float
    fuel: float
    position: Position


class State(Enum):
    IDLE = 0
    DRIVE = 1
    IN_STOP = 2
    OBSTACLE = 3
    ERROR = 4


class Action(Enum):
    NO_ACTION = 0
    STOP = 1
    START = 2


class AutonomyStatus(BaseModel):
    telemetry: Telemetry
    state: State
    nextStop: Station | None = None


class AutonomyCommand(BaseModel):
    stops: list[Station]
    route: str
    action: Action


class MissionCreator(MessageCreator):

    def __init__(self) -> None:
        super().__init__()
        self.action = Action.START

    def create_command(self, session_id: str, status_bytes: bytes) -> external_protocol.Command:
        device_command = internal_protocol.DeviceCommand()
        status = self._parse_status(status_bytes)
        stops, action = self._create_stops(status.nextStop, status.state)
        device_command.commandData = AutonomyCommand(
            stops=stops, route='test', action=action).json().encode()
        command = external_protocol.Command()
        command.sessionId = session_id
        command.messageCounter = 5  # TODO check order
        # TODO device
        command.deviceCommand.CopyFrom(device_command)
        return command

    def _parse_status(self, status_bytes: bytes) -> AutonomyStatus:
        try:
            return AutonomyStatus.parse_raw(status_bytes)
        except ValidationError as e:
            logging.error(f'Status validation failed: {e}')
            raise ValueError from None

    def _create_stops(self, next_stop: Station | None, state: State) -> tuple[list[Station], Action]:
        if next_stop is None:
            self.stops: list[Station] = [Station('Hrnčířská', Position(1, 2, 3)),
                                         Station('Semillaso', Position(4, 5, 6)),
                                         Station('Česká', Position(7, 8, 9))]
            return self.stops, self.action

        if state == State.IN_STOP and self.action == Action.START:
            self.action = Action.STOP
            self.stops.pop(0)
        else:
            self.action = Action.START
        return self.stops, self.action
