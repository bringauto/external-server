import logging
import threading
from queue import Queue

from external_server.checker.checker import Checker


class AcknowledgmentChecker(Checker):
    def __init__(self, exc: Exception) -> None:
        super().__init__(exc)
        self.messages: Queue[tuple[int, threading.Timer]] = Queue()
        self.received_acks: list[int] = []
        self.counter = 0

    def add_ack(self) -> int:
        self.counter += 1
        timer = threading.Timer(Checker.TIMEOUT, super()._set_time_out)
        timer.start()
        self.messages.put((self.counter, timer))
        return self.counter

    def remove_ack(self, msg_counter: int) -> None:
        if self.messages.empty() or msg_counter != self.messages.queue[0][0]:
            self.received_acks.append(msg_counter)
            logging.warning(f"Command response message has been recieved in bad order: {msg_counter}")
            return
        self._pop_timer()
        logging.info(f"Received Command response message was acknowledged, messageCounter: {msg_counter}")
        while self.received_acks:
            counter = self.messages.queue[0][0]
            if counter in self.received_acks:
                self._pop_timer()
                self.received_acks.remove(counter)
                logging.info(f"Older Command response message was acknowledged, messageCounter: {counter}")
                continue
            return

    def _pop_timer(self) -> None:
        _, timer = self.messages.get()
        timer.cancel()
        timer.join()

    def reset(self) -> None:
        while not self.messages.empty():
            self._pop_timer()
        self.received_acks.clear()
        self.time_out.clear()
