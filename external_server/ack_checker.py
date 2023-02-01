import logging
import threading


class AcknowledgmentChecker:

    TIME_OUT = 30

    def __init__(self) -> None:
        self.messages: list[tuple[int, threading.Timer]] = []
        self.recieved_acks: list[int] = []
        self.counter = 0
        self.time_out = threading.Event()

    def add_ack(self) -> int:
        self.counter += 1
        timer = threading.Timer(AcknowledgmentChecker.TIME_OUT, self._set_time_out)
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
        _, timer = self.messages.pop(0)
        timer.cancel()
        logging.info(f"Received Command response message was acknowledged, messageCounter: {msg_counter}")
        while self.recieved_acks:
            for counter, _ in self.messages:
                if counter in self.recieved_acks:
                    _, timer = self.messages.pop(0)
                    timer.cancel()
                    self.recieved_acks.remove(counter)
                    logging.info(f"Older Command response message was acknowledged, messageCounter: {counter}")
                    break
                else:
                    return

    def check_time_out(self) -> bool:
        return self.time_out.is_set()

    def reset(self) -> None:
        while self.messages:
            _, timer = self.messages.pop(0)
            timer.cancel()
        self.recieved_acks.clear()
        self.time_out.clear()
