import logging
import threading


class AcknowledgmentChecker:

    TIMER = 30

    def __init__(self) -> None:
        self.messages: list[int, threading.Timer] = []
        self.recieved_acks: int = []
        self.counter = 0
        self.event = threading.Event()

    def get_next_counter(self) -> None:
        self.counter += 1
        timer = threading.Timer(AcknowledgmentChecker.TIMER, self._set_event)
        timer.start()
        self.messages.append((self.counter, timer))
        return self.counter

    def _set_event(self) -> None:
        self.event.set()

    def check_command_response(self, command_counter: int) -> None:
        if not self.messages or command_counter != self.messages[0][0]:
            self.recieved_acks.append(command_counter)
            logging.warning("Command response message has been recieved in bad order")
            return
        _, timer = self.messages.pop(0)
        timer.cancel()
        logging.info(f"Received Command response message was acknowledged, messageCounter: {command_counter}")
        while self.recieved_acks:
            for counter, _ in self.messages:
                if counter in self.recieved_acks:
                    _, timer = self.messages.pop(0)
                    timer.cancel()
                    self.recieved_acks.remove(counter)
                    logging.info(f"Older Command response message was acknowledged, messageCounter: {command_counter}")
                    break
                else:
                    return

    def check_timer(self) -> bool:
        return self.event.is_set()

    def reset(self) -> None:
        while self.messages:
            _, timer = self.messages.pop(0)
            timer.cancel()
        self.recieved_acks.clear()
        self.event.clear()
