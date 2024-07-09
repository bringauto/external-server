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

    def next_published_msg(self, topic: str) -> _MQTTMessage:
        return subscribe.simple(topic, hostname=self._DEFAULT_HOST, port=self._port)

    def publish_message(self, topic: str, payload: str) -> None:
        publish.single(topic, payload, hostname=self._DEFAULT_HOST, port=self._port)

    def start(self):
        assert self.broker_process is None
        broker_script = self._script_path
        self.broker_process = subprocess.Popen(["python", broker_script, f"--port={self._port}"])
        assert isinstance(self.broker_process, subprocess.Popen)

    def stop(self):
        """Stop the broker process to stop all communication and free up the port."""
        if self.broker_process:
            self.broker_process.terminate()
            self.broker_process.wait()
            self.broker_process = None
