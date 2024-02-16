import logging
import random
import string
from queue import Queue, Empty
import sys
import ssl

import paho.mqtt.client as mqtt

sys.path.append("lib/fleet-protocol/protobuf/compiled/python")

import ExternalProtocol_pb2 as external_protocol
from external_server.event_queue import EventQueueSingleton, EventType
import external_server.constants as constants

class MqttClient:
    """
    A class representing an MQTT client.

    Args:
    - company_name (str): The name of the company.
    - car_name (str): The name of the car.

    Attributes:
    - publish_topic (str): The topic to publish messages to.
    - received_msgs (Queue[external_protocol.ExternalClient]): A queue to store received messages.
    - mqtt_client (mqtt.Client): The MQTT client instance.
    - _is_connected (bool): Indicates whether the client is connected to the MQTT broker.
    """

    def __init__(self, company_name: str, car_name: str) -> None:
        self._logger = logging.getLogger(self.__class__.__name__)

        self._publish_topic = f"{company_name}/{car_name}/external_server"
        self._subscribe_topic = f"{company_name}/{car_name}/module_gateway"
        self._received_msgs: Queue[external_protocol.ExternalClient] = Queue()
        self._mqtt_client = mqtt.Client(
            client_id="".join(random.choices(string.ascii_uppercase + string.digits, k=20)),
            protocol=mqtt.MQTTv311,
            reconnect_on_failure=True
        )
        # TODO reason these values
        self._mqtt_client.max_queued_messages_set(constants.MAX_QUEUED_MESSAGES)

        self._event_queue = EventQueueSingleton()
        self._is_connected = False

    def set_tls(self, ca_certs: str, certfile: str, keyfile: str) -> None:
        """
        Set the TLS configuration for the MQTT client.

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

    def init(self) -> None:
        """
        Initialize the MQTT client.
        """
        self._mqtt_client.on_connect = self._on_connect
        self._mqtt_client.on_disconnect = self._on_disconnect
        self._mqtt_client.on_message = self._on_message

    def _on_connect(self, client, _userdata, _flags, _rc):
        """
        Callback function for handling connection events.

        Args:
        - client (mqtt.Client): The MQTT client instance.
        - _userdata: The user data associated with the client.
        - _flags:
        - _rc (int): The return code indicating the reason for disconnection.
        - _properties: The properties associated with the disconnection event.
        """
        self._is_connected = True
        self._logger.info("Server connected to MQTT broker")
        client.subscribe(self._subscribe_topic, qos=constants.QOS)

    def _on_disconnect(self, _client, _userdata, ret_code) -> None:
        """
        Callback function for handling disconnection events.

        Args:
        - _client (mqtt.Client): The MQTT client instance.
        - _userdata: The user data associated with the client.
        - ret_code (int): The return code indicating the reason for disconnection.
        - _properties: The properties associated with the disconnection event.
        """
        self._is_connected = False
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
        message_external_client = external_protocol.ExternalClient().FromString(message.payload)
        self._received_msgs.put(message_external_client)
        self._event_queue.add_event(event_type=EventType.RECEIVED_MESSAGE)

    def connect(self, ip_address: str, port: int) -> None:
        """
        Connect to the MQTT broker.

        Args:
        - ip_address (str): The IP address of the MQTT broker.
        - port (int): The port number of the MQTT broker.
        """
        self._mqtt_client.connect(ip_address, port=port, keepalive=constants.KEEPALIVE)

    def start(self) -> None:
        """
        Start the MQTT client's event loop.
        """
        self._mqtt_client.loop_start()

    def stop(self) -> None:
        """
        Stop the MQTT client's event loop.
        """
        self._mqtt_client.loop_stop()
        self._is_connected = False

    def publish(self, msg: external_protocol.ExternalServer) -> None:
        """
        Publish a message to the MQTT broker.

        Args:
        - msg (external_protocol.ExternalServer): The message to publish.
        """
        self._mqtt_client.publish(self._publish_topic, msg.SerializeToString(), qos=constants.QOS)

    def get(self, timeout: int | None = None) -> external_protocol.ExternalClient | None:
        """Returns message from MqttClient
        Parameters
        ----------
        timeout:int
            Timeout to wait for received message. If timeout is None, function blocks
                until message is available.
        """
        try:
            return self._received_msgs.get(block=True, timeout=timeout)
        except Empty:
            return None

    @property
    def is_connected(self) -> bool:
        """
        Check if the MQTT client is connected to the broker.

        Returns:
        - bool: True if connected, False otherwise.
        """
        return self._is_connected
