"""Custom exceptions used in the external server"""


class ConnectSequenceFailure(Exception):
    pass


class CommunicationException(Exception):
    pass


class CouldNotConnectToBroker(Exception):
    pass


class UnexpectedMQTTDisconnect(Exception):
    pass


class MQTTCommunicationError(Exception):
    pass


class NoMessage(Exception):
    pass


class SessionTimeout(Exception):
    pass


class CommandResponseTimeout(Exception):
    pass


class StatusTimeout(Exception):
    pass
