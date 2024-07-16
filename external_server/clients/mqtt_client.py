import logging.config
import json
import random
import string
from queue import Queue, Empty
import sys
import ssl
from typing import Optional, Any

sys.path.append("lib/fleet-protocol/protobuf/compiled/python")

import paho.mqtt.client as mqtt
from paho.mqtt.client import (
    error_string as _error_string,
    MQTTErrorCode as _MQTTErrorCode,
    MQTTMessage as MQTTMessage
)
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


def create_mqtt_client() -> mqtt.Client:
    client_id = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    client = mqtt.Client(
        callback_api_version=CallbackAPIVersion.VERSION2,
        client_id=client_id,
        protocol=mqtt.MQTTv311,
        reconnect_on_failure=True,
    )
    client.max_queued_messages_set(_MAX_QUEUED_MESSAGES)
    return client


def mqtt_error(code: int) -> str:
    enum_val = _MQTTErrorCode._value2member_map_[code]
    return _error_string(enum_val)  # type: ignore


class MQTTClientAdapter:
    """Class binding together a MQTT client and queues for storing received messages and events.

    Enables to set up in advance the timeout for getting messages from the queues and connection
    parameters for the MQTT client.
    """

    _EXTERNAL_SERVER_SUFFIX = "external_server"
    _MODULE_GATEWAY_SUFFIX = "module_gateway"

    def __init__(
        self, company: str, car_name: str, timeout: float, broker_host: str, broker_port: int
    ) -> None:

        self._publish_topic = f"{company}/{car_name}/{MQTTClientAdapter._EXTERNAL_SERVER_SUFFIX}"
        self._subscribe_topic = f"{company}/{car_name}/{MQTTClientAdapter._MODULE_GATEWAY_SUFFIX}"
        self._received_msgs: Queue[_ExternalClientMsg] = Queue()
        self._mqtt_client = create_mqtt_client()
        self._event_queue = EventQueueSingleton()
        self._timeout = timeout
        self._keepalive = _KEEPALIVE
        self._broker_host = broker_host
        self._broker_port = broker_port
        self._set_up_callbacks()

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
        code = self._mqtt_client.connect(self._broker_host, self._broker_port, _KEEPALIVE)
        if code==mqtt.MQTT_ERR_SUCCESS:
            self._mqtt_client.subscribe(self._subscribe_topic, qos=_QOS)
            self._start_client_loop()
        else:
            _logger.error(f"Failed to connect to broker: {self._broker_host}:{self._broker_port}")

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
            return message
        except Empty:
            return None

    def publish(self, msg: _ExternalServerMsg) -> None:
        """Publish a message to the MQTT broker."""
        payload = msg.SerializeToString()
        code = self._mqtt_client.publish(self._publish_topic, payload, qos=_QOS).rc
        if code == mqtt.MQTT_ERR_SUCCESS:
            _logger.debug(f"Published message on topic '{self._publish_topic}'")
        else:
            _logger.error(f"Failed to publish message: {mqtt_error(code)}")

    def start(self) -> None:
        """Start the MQTT client's event loop."""
        code = self._mqtt_client.loop_start()
        if code == mqtt.MQTT_ERR_SUCCESS:
            _logger.debug("Started MQTT client's event loop")
        else:
            _logger.error(f"Failed to start MQTT client's event loop: {mqtt_error(code)}")

    def stop(self) -> None:
        """Stop the MQTT client's event loop. Do nothing, if the loop is not running."""
        cli = self._mqtt_client
        if cli._thread and cli._thread.is_alive():
            code = self._mqtt_client.loop_stop()
            if code == mqtt.MQTT_ERR_SUCCESS:
                _logger.debug("Stopped MQTT client's event loop")
            else :
                _logger.error(f"Failed to stop MQTT client's event loop: {mqtt_error(code)}")

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


    def _start_client_loop(self) -> None:
        code = self._mqtt_client.loop_start()
        if code == mqtt.MQTT_ERR_SUCCESS:
            _logger.info(f"Connected to broker: {self._broker_host}:{self._broker_port}")
        else:
            _logger.error(f"Failed to start MQTT client's event loop: {mqtt_error(code)}")

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

    def _on_disconnect(self, client: mqtt.Client, _userdata: Any, _flags: Any, ret_code, properties) -> None:
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

    def _on_message(self, client: mqtt.Client, _userdata, message: MQTTMessage) -> None:
        """Callback function for handling incoming messages.

        The message is added to the received messages queue, if the topic matches the subscribe topic,
        and an event is added to the event queue.

        Args:
        - _client (mqtt.Client): The MQTT client instance.
        - _userdata: The user data associated with the client.
        - message (mqtt.MQTTMessage): The received MQTT message.
        """
        _logger.debug(f"Received message: {message}")
        if message.topic == self._subscribe_topic:
            self._received_msgs.put(_ExternalClientMsg().FromString(message.payload))
            self._event_queue.add_event(event_type=EventType.RECEIVED_MESSAGE)

    def _set_up_callbacks(self) -> None:
        self._mqtt_client.on_connect = self._on_connect
        self._mqtt_client.on_disconnect = self._on_disconnect
        self._mqtt_client.on_message = self._on_message
        self.callback_test()

    def callback_test(self) -> None:
        # test if the message callback is set up correctly
        test_msg = MQTTMessage()
        test_msg.payload = _ExternalClientMsg().SerializeToString()
        test_msg.topic = self._subscribe_topic.encode()  # type: ignore

        assert self._mqtt_client._on_message is not None
        self._mqtt_client._on_message(self._mqtt_client, None, test_msg)
        assert self._received_msgs.get(block=True, timeout=0.1) is not None

        self._mqtt_client._on_message(self._mqtt_client, None, test_msg)
        result = self.get_message(ignore_timeout=True)
        assert result is not None
