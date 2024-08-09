"""Custom exceptions used in the external server"""


class ConnectSequenceFailure(Exception):
    pass


class CommunicationException(Exception):
    pass


class UnexpectedMQTTDisconnect(CommunicationException):
    pass


class NoPublishedMessage(CommunicationException):
    pass


class SessionTimeout(CommunicationException):
    pass


class CommandResponseTimeout(CommunicationException):
    pass


class StatusTimeout(CommunicationException):
    pass
