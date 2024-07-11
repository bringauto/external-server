import logging
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
    ExternalServer as _ExternalServerMsg
)
from external_server.models.event_queue import EventQueueSingleton, EventType


# maximum number of messages in outgoing queue
# value reasoning: external server can handle approximatelly 20 devices
_MAX_QUEUED_MESSAGES = 20
# value reasoning: keepalive is half of the default timeout in Fleet Protocol (30 s)
_KEEPALIVE = 15
# Quality of Service used by Mqtt client
_QOS = 1


class MQTTClient:
    """Class representing an MQTT client."""

    def __init__(self, company_name: str, car_name: str, timeout: float) -> None:
        self._logger = logging.getLogger(self.__class__.__name__)
        self._publish_topic = f"{company_name}/{car_name}/external_server"
        self._subscribe_topic = f"{company_name}/{car_name}/module_gateway"
        self._received_msgs: Queue[_ExternalClientMsg] = Queue()
        self._mqtt_client = mqtt.Client(
            callback_api_version=CallbackAPIVersion.VERSION2,
            client_id=MQTTClient.generate_client_id(),
            protocol=mqtt.MQTTv311,
            reconnect_on_failure=True
        )
        # TODO reason these values
        self._mqtt_client.max_queued_messages_set(_MAX_QUEUED_MESSAGES)
        self._event_queue = EventQueueSingleton()
        self._timeout = timeout
        self._broker_ip = ""
        self._broker_port = 0
        self._keepalive = _KEEPALIVE

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

    def connect_to_broker(self, broker_ip: str, broker_port: int) -> None:
        self._mqtt_client.connect(broker_ip, port=broker_port, keepalive=_KEEPALIVE)
        self._broker_ip = broker_ip
        self._broker_port = broker_port

    def block_and_get_message(self) -> _ExternalClientMsg | None:
        """Returns message from MQTTClient.

        Function blocks until message is available.
        """
        try:
            return self._received_msgs.get(block=True)
        except Empty:
            return None

    def get_message(self) -> _ExternalClientMsg | None:
        """Returns message from MQTTClient.

        Function blocks until message is available or until timeout is reached - in the latter
        case function returns `None`.
        """
        try:
            msgs = self._received_msgs.get(block=True, timeout=self._timeout)
            return msgs
        except Empty:
            return None

    def publish(self, msg: _ExternalServerMsg) -> None:
        """Publish a message to the MQTT broker."""
        payload = msg.SerializeToString()
        self._mqtt_client.publish(self._publish_topic, payload, qos=_QOS)

    def set_tls(self, ca_certs: str, certfile: str, keyfile: str) -> None:
        """Set the TLS configuration for the MQTT client.

        Args:
        - ca_certs (str): The path to the CA certificates file.
        - certfile (str): The path to the client certificate file.
        - keyfile (str): The path to the client private key file.
        """
        if self._mqtt_client is not None:
            # maybe use tls_version= ssl.PROTOCOL_TLS_SERVER
            self._mqtt_client.tls_set(
                ca_certs=ca_certs,
                certfile=certfile,
                keyfile=keyfile,
                tls_version=ssl.PROTOCOL_TLS_CLIENT,
            )
            self._mqtt_client.tls_insecure_set(False)

    def set_up_callbacks(self) -> None:
        self._mqtt_client.on_connect = self._on_connect
        self._mqtt_client.on_disconnect = self._on_disconnect
        self._mqtt_client.on_message = self._on_message

    def start(self) -> None:
        """Start the MQTT client's event loop."""
        self._mqtt_client.loop_start()

    def connect_and_start(self) -> None:
        """Start the MQTT client's event loop."""
        self.set_up_callbacks()
        self.connect_to_broker(self._broker_ip, self._broker_port)
        self._mqtt_client.loop_start()

    def stop(self) -> None:
        """Stop the MQTT client's event loop."""
        self._mqtt_client.loop_stop()
        self._mqtt_client.disconnect()

    def _on_connect(self, client: mqtt.Client, _userdata, _flags, _rc, properties):
        """
        Callback function for handling connection events.

        Args:
        - client (mqtt.Client): The MQTT client instance.
        - _userdata: The user data associated with the client.
        - _flags:
        - _rc (int): The return code indicating the reason for disconnection.
        - _properties: The properties associated with the disconnection event.
        """
        self._logger.info("Server connected to MQTT broker")
        client.subscribe(self._subscribe_topic, qos=_QOS)

    def _on_disconnect(self, _client, _userdata, _flags, ret_code, properties) -> None:
        """
        Callback function for handling disconnection events.

        Args:
        - _client (mqtt.Client): The MQTT client instance.
        - _userdata: The user data associated with the client.
        - ret_code (int): The return code indicating the reason for disconnection.
        - _properties: The properties associated with the disconnection event.
        """
        self._logger.info("Server disconnected from MQTT broker")
        self._received_msgs.put(False)
        self._event_queue.add_event(event_type=EventType.MQTT_BROKER_DISCONNECTED)

    def _on_message(self, _client: mqtt.Client, _userdata, message: mqtt.MQTTMessage) -> None:
        """
        Callback function for handling incoming messages.

        Args:
        - _client (mqtt.Client): The MQTT client instance.
        - _userdata: The user data associated with the client.
        - message (mqtt.MQTTMessage): The received MQTT message.
        """
        if message.topic != self._subscribe_topic:
            return
        message_external_client = _ExternalClientMsg().FromString(message.payload)
        self._received_msgs.put(message_external_client)
        self._event_queue.add_event(event_type=EventType.RECEIVED_MESSAGE)


    @staticmethod
    def generate_client_id() -> str:
        return "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
