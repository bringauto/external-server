import logging
import threading


class AcknowledgmentChecker:

    TIMER = 30

    def __init__(self) -> None:
        self.command_responses = []
        self.recieved_acks = []
        self.command_counter = 0
        self.event = threading.Event()

    def get_next_counter(self) -> None:
        self.command_counter += 1
        timer = threading.Timer(AcknowledgmentChecker.TIMER, self._set_event)
        timer.start()
        self.command_responses.append((self.command_counter, timer))
        return self.command_counter

    def _set_event(self) -> None:
        self.event.set()

    def check_command_response(self, command_counter: int) -> None:
        if not self.command_responses or command_counter != self.command_responses[0][0]:
            self.recieved_acks.append(command_counter)
            logging.warning("Command response message has been recieved in bad order") # probably change this log
            return
        self.command_responses.pop(0)
        logging.info(f"Received Command response message was acknowledged, messageCounter: {command_counter}")
        while self.recieved_acks:
            for counter, _ in self.command_responses:
                if counter in self.recieved_acks:
                    self.command_responses.pop(0)
                    self.recieved_acks.remove(counter)
                    logging.info(f"Older Command response message was acknowledged, messageCounter: {command_counter}")
                    break
                else:
                    return

    def check_timer(self) -> bool:
        return self.event.is_set()

    def reset(self) -> None:
        self.command_responses.clear()
        self.event.clear()
