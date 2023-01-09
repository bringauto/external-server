from abc import ABC, abstractmethod

import external_server.protobuf.ExternalProtocol_pb2 as external_protocol


class MessageCreator(ABC):

    def create_connect_response(self, session_id: str) -> external_protocol.ConnectResponse:
        connect_response = external_protocol.ConnectResponse()
        # TODO implement ALREADY_LOGGED
        connect_response.type = external_protocol.ConnectResponse.Type.OK
        connect_response.sessionId = session_id
        return connect_response

    def create_status_response(self, session_id: str, message_counter: int) -> external_protocol.StatusResponse:
        status_response = external_protocol.StatusResponse()
        status_response.sessionId = session_id
        status_response.type = external_protocol.StatusResponse.Type.OK
        status_response.messageCounter = message_counter + 1  # TODO check order
        return status_response

    @abstractmethod
    def create_command(self, session_id: str, status_bytes: bytes) -> external_protocol.Command:
        pass
