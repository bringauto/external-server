import os
import subprocess
import sys

sys.path.append("lib/mqtt-testing/interoperability")

import external_server as _external_server
from paho.mqtt.client import MQTTMessage as _MQTTMessage
import paho.mqtt.subscribe as subscribe  # type: ignore


DEFAULT_PORT = 1883


class MQTTBrokerTest:

    _DEFAULT_HOST = "127.0.0.1"

    def __init__(self, start: bool = False, port: int = DEFAULT_PORT):
        self.broker_process = None
        self._port = port
        if start:
            self.start()

    @property
    def host(self):
        return self._DEFAULT_HOST

    def next_published_msg(self, topic: str) -> _MQTTMessage:
        return subscribe.simple(topic, hostname=self._DEFAULT_HOST, port=self._port)

    def start(self):
        assert self.broker_process is None
        root_dir = os.path.dirname(_external_server.DIR)
        mqtt_broker_script = os.path.join(root_dir, "lib/mqtt-testing/interoperability/startbroker.py")
        self.broker_process = subprocess.Popen(["python", mqtt_broker_script, f"--port={self._port}"])
        assert isinstance(self.broker_process, subprocess.Popen)

    def stop(self):
        if self.broker_process:
            self.broker_process.terminate()
            self.broker_process.wait()