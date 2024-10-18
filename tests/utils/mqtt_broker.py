from __future__ import annotations
import os
import sys
import subprocess
import logging
import time
import threading
import contextlib
from typing import Any

import paho.mqtt.publish as publish  # type: ignore
import paho.mqtt.client as client  # type: ignore

import external_server as _external_server
from ExternalProtocol_pb2 import ExternalClient as Ex  # type: ignore


logger = logging.getLogger("MQTT Broker")
logger.setLevel(logging.ERROR)


_EXTERNAL_SERVER_PATH = _external_server.PATH


class MQTTBrokerTest:

    _running_broker_processes: list[subprocess.Popen] = []
    _DEFAULT_HOST = "127.0.0.1"
    _DEFAULT_PORT = 1883

    def __init__(
        self,
        *client_topics: str,
        start: bool = False,
        port: int = _DEFAULT_PORT,
        kill_others: bool = True,
    ):
        if kill_others:  # pragma: no cover
            MQTTBrokerTest.kill_all_test_brokers()
        self._process: None | subprocess.Popen = None
        self._port = port
        self._host = self._DEFAULT_HOST
        self._script_path = os.path.join(
            _EXTERNAL_SERVER_PATH, "tests/utils/mqtt-testing/interoperability/startbroker.py"
        )
        self._client = client.Client(client.CallbackAPIVersion.VERSION2)
        self._messages: dict[str, list[bytes]] = dict()
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._topics = client_topics
        self._new_message = threading.Event()
        if start:
            self.start()

    @property
    def client_test(self) -> client.Client:
        """Return the client object for testing."""
        return self._client

    def messages(self, topic: str) -> list[bytes]:
        return self._messages.get(topic, [])

    def clear_messages(self, topic: str) -> None:
        if topic in self._messages:
            del self._messages[topic]

    def all_messages(self) -> dict[str, list[bytes]]:
        return self._messages.copy()

    @classmethod
    def running_processes(cls) -> list[subprocess.Popen]:
        return cls._running_broker_processes

    @classmethod
    def kill_all_test_brokers(cls):  # pragma: no cover
        for process in cls._running_broker_processes:
            process.kill()
            with contextlib.suppress(ValueError):
                cls._running_broker_processes.remove(process)

    @property
    def is_running(self) -> bool:
        return self._process is not None

    def _on_connect(self, client: client.Client, data: Any, flags, rc, properties) -> None:
        assert self._client.is_connected()

    def _on_message(self, client: client.Client, data: Any, message: client.MQTTMessage) -> None:
        """Callback function for handling incoming messages.

        The message is added to the received messages queue, if the topic matches the subscribe topic,
        and an event is added to the event queue.

        Args:
        - `client` The MQTT client instance.
        - `data` The user data associated with the client.
        - `message` (mqtt.MQTTMessage): The received MQTT message.
        """
        print(f"Received message on topic '{message.topic}'.")
        if not self._messages.get(message.topic):
            self._messages[message.topic] = list()
        self._messages[message.topic].append(message.payload)
        self._new_message.set()

    def wait_for_messages(
        self, topic: str, n: int = 1, timeout: float = 5.0, newest: bool = False
    ) -> None | list[bytes]:
        """Wait for `n` messages on the given topic.

        Args:
        - `topic` (str): The topic to wait for messages on.
        - `n` (int): The number of messages to wait for.
        - `timeout` (float): The maximum time to wait for the messages in seconds.

        Returns:
        - `None`: If the timeout occurred before receiving the expected messages.
        - `list[bytes]`: The list of received messages if the expected number was received.
        """
        logger.info(f"Test broker: Waiting for {n} messages on topic {topic}")
        while True:
            new_msg = self._new_message.wait(timeout=timeout)
            self._new_message.clear()
            if not new_msg:  # timeout
                print(f"Timeout. Received only {len(self.messages(topic))} messages.")
                return None
            else:
                messages = self.messages(topic)
                if len(messages) > n:
                    if newest:
                        return messages[-n:]
                    else:
                        return messages[:n]
                elif len(messages) == n:
                    return messages

    def publish(self, topic: str, *payload: str | bytes) -> None:
        if not payload:  # pragma: no cover
            return
        payload_list = []
        for p in payload:
            if isinstance(p, Ex):
                payload_list.append(p.SerializeToString())
            else:
                payload_list.append(p)
        if len(payload_list) == 1:
            publish.single(topic, payload_list[0], hostname=self._host, port=self._port)
        else:
            payload_list = [(topic, p) for p in payload_list]
            publish.multiple(payload_list, hostname=self._host, port=self._port)
            logger.info(f"Test broker: Published messages to topic {topic}.")

    def start(self, interval: float = 0.01, timeout: float = 1.0) -> None:
        broker_script = self._script_path
        self._process = subprocess.Popen([sys.executable, broker_script, f"--port={self._port}"])
        print(f"Started test broker on host {self._host} and port {self._port}")
        self._running_broker_processes.append(self._process)

        t = time.time()
        while time.time() - t < timeout:
            try:
                self._client.connect(self._host, self._port)
                self._client.loop_start()
                for topic in self._topics:
                    self._client.subscribe(topic)
                break
            except ConnectionError:
                time.sleep(interval)
            except Exception as e:
                print("Cannot start test broker due to unexpected error")
                raise e

        t = time.time()
        while time.time() - t < timeout:
            if self._client.is_connected():
                break
            else:
                time.sleep(interval)

    def stop(self):
        """Stop the broker process to stop all communication and free up the port."""
        self._client.loop_stop()
        self._client.disconnect()
        while self._client.is_connected():
            time.sleep(0.1)

        if self._process:
            self._process.terminate()
            self._process.wait()
            assert self._process.poll() is not None
            if self._process in self._running_broker_processes:  # pragma: no cover
                self._running_broker_processes.remove(self._process)
            self._process = None
            MQTTBrokerTest.kill_all_test_brokers()
        time.sleep(0.1)
