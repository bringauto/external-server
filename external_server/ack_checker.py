import logging
import threading

from external_server.timeout import TIMEOUT


class AcknowledgmentChecker:

    def __init__(self) -> None:
        self.messages: list[tuple[int, threading.Timer]] = []
        self.recieved_acks: list[int] = []
        self.counter = 0
        self.time_out = threading.Event()

    def add_ack(self) -> int:
        self.counter += 1
        timer = threading.Timer(TIMEOUT, self._set_time_out)
        timer.start()
        self.messages.append((self.counter, timer))
        return self.counter

    def _set_time_out(self) -> None:
        self.time_out.set()

    def remove_ack(self, msg_counter: int) -> None:
        if not self.messages or msg_counter != self.messages[0][0]:
            self.recieved_acks.append(msg_counter)
            logging.warning("Command response message has been recieved in bad order")
            return
        self._pop_timer()
        logging.info(f"Received Command response message was acknowledged, messageCounter: {msg_counter}")
        while self.recieved_acks:
            for counter, _ in self.messages:
                if counter in self.recieved_acks:
                    self._pop_timer()
                    self.recieved_acks.remove(counter)
                    logging.info(f"Older Command response message was acknowledged, messageCounter: {counter}")
                    break
                else:
                    return

    def _pop_timer(self) -> None:
        _, timer = self.messages.pop(0)
        timer.cancel()
        timer.join()

    def check_time_out(self) -> bool:
        return self.time_out.is_set()

    def reset(self) -> None:
        while self.messages:
            self._pop_timer()
        self.recieved_acks.clear()
        self.time_out.clear()
