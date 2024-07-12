import os
import subprocess
import logging.config
import json

import external_server as _external_server
from paho.mqtt.client import MQTTMessage as _MQTTMessage
import paho.mqtt.subscribe as subscribe  # type: ignore
import paho.mqtt.publish as publish  # type: ignore
from ExternalProtocol_pb2 import ExternalClient as Ex  # type: ignore


logger = logging.getLogger(__name__)
with open("./config/logging.json", "r") as f:
    logging.config.dictConfig(json.load(f))


_EXTERNAL_SERVER_PATH = _external_server.PATH


class MQTTBrokerTest:

    _DEFAULT_HOST = "127.0.0.1"
    _DEFAULT_PORT = 1883

    def __init__(self, start: bool = False, port: int = _DEFAULT_PORT):
        self.broker_process = None
        self._port = port
        self._host = self._DEFAULT_HOST
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
        logger.debug(f"Waiting for {n} messages on topic {topic}")
        result = subscribe.simple(
            [topic], hostname=self._host, port=self._port, msg_count=n
        )
        if n == 1:
            return [result]
        else:
            return result

    def publish_messages(self, topic: str, *payload: str | bytes) -> None:
        payload_list = []
        for p in payload:
            if isinstance(p, Ex):
                payload_list.append(p.SerializeToString())
            else:
                payload_list.append(p)
        if len(payload_list) == 0:
            return
        elif len(payload_list) == 1:
            publish.single(topic, payload_list[0], hostname=self._host, port=self._port)
            logger.debug(f"Published message to topic {topic}: {payload_list[0]}")
        else:
            try:
                payload_list = [(topic, p) for p in payload_list]
                publish.multiple(payload_list, hostname=self._host, port=self._port)
                logger.debug(f"Published messages to topic {topic}: {payload_list}")
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
