"""Custom exceptions used in the external server"""

class ConnectSequenceException(Exception):
    pass




class NormalCommunicationException(Exception):
    pass


class UnexpectedDisconnectionExc(NormalCommunicationException):
    def __init__(self):
        super().__init__("Unexpected disconnection")


class ConnectSessionTimeOutExc(NormalCommunicationException):
    def __init__(self) -> None:
        super().__init__("Connected session has been timed out")


class CommandResponseTimeOutExc(NormalCommunicationException):
    def __init__(self):
        super().__init__("Command response message has not been received in time")


class StatusTimeOutExc(NormalCommunicationException):
    def __init__(self) -> None:
        super().__init__("Status messages has not been received in time")
