import external_server.protobuf.InternalProtocol_pb2 as internal_protocol


class MessageParser:

    def parse_connect(self, data: bytes) -> internal_protocol.DeviceConnect:
        message = internal_protocol.DeviceConnect.FromString(data)
        return message

    def parse_status(self, data: bytes) -> bytes:
        message = internal_protocol.DeviceStatus.FromString(data)
        return message.statusData
