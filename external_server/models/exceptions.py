"""Custom exceptions used in the external server"""


class ConnectSequenceFailure(Exception):
    pass


class CommunicationException(Exception):
    pass


class ClientDisconnected(CommunicationException):
    def __init__(self):
        super().__init__("Unexpected disconnection")


class SessionTimeout(CommunicationException):
    def __init__(self) -> None:
        super().__init__("Session has not been received in time")


class CommandResponseTimeout(CommunicationException):
    def __init__(self) -> None:
        super().__init__("Command response message has not been received in time")


class StatusTimeout(CommunicationException):
    def __init__(self) -> None:
        super().__init__("Status messages has not been received in time")
