"""Custom exceptions used in the external server"""


class ConnectSequenceException(Exception):
    pass


class CommunicationException(Exception):
    pass


class ClientDisconnectedExc(CommunicationException):
    def __init__(self):
        super().__init__("Unexpected disconnection")


class ConnectSessionTimeOutExc(CommunicationException):
    def __init__(self) -> None:
        super().__init__("Connected session has been timed out")


class CommandResponseTimeOutExc(CommunicationException):
    def __init__(self) -> None:
        super().__init__("Command response message has not been received in time")


class StatusTimeOutExc(CommunicationException):
    def __init__(self) -> None:
        super().__init__("Status messages has not been received in time")
