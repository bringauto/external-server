import logging.config
import json
import random
import string
from queue import Queue, Empty
import sys
import ssl
from typing import Optional

sys.path.append("lib/fleet-protocol/protobuf/compiled/python")

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

from ExternalProtocol_pb2 import (  # type: ignore
    ExternalClient as _ExternalClientMsg,
    ExternalServer as _ExternalServerMsg,
)
from external_server.models.event_queue import EventQueueSingleton, EventType


# maximum number of messages in outgoing queue
# value reasoning: external server can handle approximatelly 20 devices
_MAX_QUEUED_MESSAGES = 20
# value reasoning: keepalive is half of the default timeout in Fleet Protocol (30 s)
_KEEPALIVE = 15
# Quality of Service used by Mqtt client
_QOS = 1


_logger = logging.getLogger(__name__)
with open("./config/logging.json", "r") as f:
    logging.config.dictConfig(json.load(f))


def _create_mqtt_client(subscribe_topic: str) -> mqtt.Client:
    client_id = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    client = mqtt.Client(
        callback_api_version=CallbackAPIVersion.VERSION2,
        client_id=client_id,
        protocol=mqtt.MQTTv311,
        reconnect_on_failure=True,
    )
    client.subscribe(subscribe_topic, qos=_QOS)
    client.max_queued_messages_set(_MAX_QUEUED_MESSAGES)
    return client


class MQTTClient:
    """Class representing an MQTT client."""

    _EXTERNAL_SERVER_SUFFIX = "external_server"
    _MODULE_GATEWAY_SUFFIX = "module_gateway"

    def __init__(
        self, company: str, car_name: str, timeout: float, broker_host: str, broker_port: int
    ) -> None:

        self._publish_topic = f"{company}/{car_name}/{MQTTClient._EXTERNAL_SERVER_SUFFIX}"
        self._subscribe_topic = f"{company}/{car_name}/{MQTTClient._MODULE_GATEWAY_SUFFIX}"
        self._received_msgs: Queue[_ExternalClientMsg] = Queue()
        self._mqtt_client = _create_mqtt_client(self._subscribe_topic)
        self._event_queue = EventQueueSingleton()
        self._timeout = timeout
        self._keepalive = _KEEPALIVE
        self._broker_host = broker_host
        self._broker_port = broker_port

    @property
    def is_connected(self) -> bool:
        return self._mqtt_client.is_connected()

    @property
    def publish_topic(self) -> str:
        """The topic to publish messages to."""
        return self._publish_topic

    @property
    def received_messages(self) -> Queue[_ExternalClientMsg]:
        """A queue to store received messages."""
        return self._received_msgs

    @property
    def subscribe_topic(self) -> str:
        return self._subscribe_topic

    @property
    def timeout(self) -> Optional[float]:
        return self._timeout

    def connect(self) -> None:
        """Connect to the MQTT broker."""
        _logger.debug(f"Connecting to broker: {self._broker_host}:{self._broker_port}")
        self._mqtt_client.connect(self._broker_host, port=self._broker_port, keepalive=_KEEPALIVE)

    def disconnect(self) -> None:
        """Disconnect from the MQTT broker."""
        if self._mqtt_client.is_connected():
            self._mqtt_client.disconnect()
            _logger.debug(f"Disconnected from MQTT broker: {self._broker_host}:{self._broker_port}")
        else:
            _logger.debug(
                "Trying to disconnect from MQTT broker, but not connected. No action is taken."
            )

    def get_message(self, ignore_timeout: bool = False) -> _ExternalClientMsg | None:
        """Returns message from MQTTClient.

        If `ignore_timeout` is `False`(default), the function blocks until message is available
        or timeout is reached (then `None` is returned).

        If `ignore_timeout` is set to `True`, the function will return only if a message is
        available.
        """
        t = None if ignore_timeout else self._timeout
        try:
            message = self._received_msgs.get(block=True, timeout=t)
            _logger.debug(f"Received message: {message}")
            return message
        except Empty:
            return None

    def publish(self, msg: _ExternalServerMsg) -> None:
        """Publish a message to the MQTT broker."""
        payload = msg.SerializeToString()
        self._mqtt_client.publish(self._publish_topic, payload, qos=_QOS)

    def start(self) -> None:
        """Start the MQTT client's event loop."""
        self._mqtt_client.loop_start()
        _logger.debug("Started MQTT client's event loop")

    def stop(self) -> None:
        """Stop the MQTT client's event loop."""
        self._mqtt_client.loop_stop()
        _logger.debug("Stopped MQTT client's event loop")

    def tls_set(self, ca_certs: str, certfile: str, keyfile: str) -> None:
        """Set the TLS configuration for the MQTT client.

        `ca_certs` - path to the CA certificates file.
        `certfile` - path to the client certificate file.
        `keyfile` - path to the client private key file.
        """
        if self._mqtt_client is not None:
            self._mqtt_client.tls_set(
                ca_certs=ca_certs,
                certfile=certfile,
                keyfile=keyfile,
                tls_version=ssl.PROTOCOL_TLS_CLIENT,
            )
            self._mqtt_client.tls_insecure_set(False)

    def update_broker_host_and_port(self, broker_host: str, broker_port: int) -> None:
        self._broker_host = broker_host
        self._broker_port = broker_port

    def _on_connect(self, client: mqtt.Client, _userdata, _flags, _rc, properties):
        """Callback function for handling connection events.

        Args:
        - client (mqtt.Client): The MQTT client instance.
        - _userdata: The user data associated with the client.
        - _flags:
        - _rc (int): The return code indicating the reason for disconnection.
        - _properties: The properties associated with the disconnection event.
        """
        _logger.info("Server connected to MQTT broker")

    def _on_disconnect(self, client: mqtt.Client, _userdata, _flags, ret_code, properties) -> None:
        """Callback function for handling disconnection events.

        Args:
        - _client (mqtt.Client): The MQTT client instance.
        - _userdata: The user data associated with the client.
        - ret_code (int): The return code indicating the reason for disconnection.
        - _properties: The properties associated with the disconnection event.
        """
        _logger.info("Server disconnected from MQTT broker")
        self._received_msgs.put(False)
        self._event_queue.add_event(event_type=EventType.MQTT_BROKER_DISCONNECTED)

    def _on_message(self, client: mqtt.Client, _userdata, message: mqtt.MQTTMessage) -> None:
        """Callback function for handling incoming messages.

        The message is added to the received messages queue, if the topic matches the subscribe topic,
        and an event is added to the event queue.

        Args:
        - _client (mqtt.Client): The MQTT client instance.
        - _userdata: The user data associated with the client.
        - message (mqtt.MQTTMessage): The received MQTT message.
        """
        if message.topic == self._subscribe_topic:
            self._received_msgs.put(_ExternalClientMsg().FromString(message))
            self._event_queue.add_event(event_type=EventType.RECEIVED_MESSAGE)

    def _set_up_callbacks(self) -> None:
        self._mqtt_client.on_connect = self._on_connect
        self._mqtt_client.on_disconnect = self._on_disconnect
        self._mqtt_client.on_message = self._on_message
