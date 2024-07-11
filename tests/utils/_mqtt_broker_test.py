import os
import subprocess

import external_server as _external_server
from paho.mqtt.client import MQTTMessage as _MQTTMessage
import paho.mqtt.subscribe as subscribe  # type: ignore
import paho.mqtt.publish as publish  # type: ignore


_EXTERNAL_SERVER_PATH = _external_server.PATH


class MQTTBrokerTest:

    _DEFAULT_HOST = "127.0.0.1"
    _DEFAULT_PORT = 1883

    def __init__(self, start: bool = False, port: int = _DEFAULT_PORT):
        self.broker_process = None
        self._port = port
        self._script_path = os.path.join(_EXTERNAL_SERVER_PATH, "lib/mqtt-testing/interoperability/startbroker.py")
        if start:
            self.start()

    @property
    def is_running(self) -> bool:
        return self.broker_process is not None

    def get_messages(self, topic: str, n: int = 1) -> list[_MQTTMessage]:
        """Return messages from the broker on the given topic.

        `n` is the number of messages to wait for and return.
        """
        result = subscribe.simple(
            topic, hostname=self._DEFAULT_HOST, port=self._port, msg_count=n
        )
        if n == 1:
            return [result]
        else:
            return result

    def publish_messages(self, topic: str, *payload: str) -> None:
        if len(payload) == 0:
            return
        elif len(payload) == 1:
            publish.single(topic, payload[0], hostname=self._DEFAULT_HOST, port=self._port)
        else:
            try:
                payload_list = [(topic, p) for p in payload]
                publish.multiple(payload_list, hostname=self._DEFAULT_HOST, port=self._port)
            except Exception as e:
                print(e)
                raise e


    def start(self):
        broker_script = self._script_path
        self.broker_process = subprocess.Popen(["python", broker_script, f"--port={self._port}"])
        assert isinstance(self.broker_process, subprocess.Popen)

    def stop(self):
        """Stop the broker process to stop all communication and free up the port."""
        if self.broker_process:
            self.broker_process.terminate()
            self.broker_process.wait()
            self.broker_process = None
