from abc import ABC, abstractmethod

import external_server.protobuf.ExternalProtocol_pb2 as external_protocol
import external_server.protobuf.InternalProtocol_pb2 as internal_protocol


class MessageCreator(ABC):

    @staticmethod
    def create_connect_response(type) -> internal_protocol.DeviceConnectResponse:
        message = internal_protocol.DeviceConnectResponse()
        message.responseType = type.value
        return message

    @abstractmethod
    def create_command(self, status_bytes: bytes) -> external_protocol.Command:
        pass
