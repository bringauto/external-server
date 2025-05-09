import secrets
import string
from queue import Queue, Empty
import ssl
from typing import Optional, Any
import time
import os
import threading

import paho.mqtt.client as mqtt
from paho.mqtt.client import (
    Client as _Client,
    _ConnectionState as _ConnectionState,
    error_string as _error_string,
    MQTTErrorCode as _MQTTErrorCode,
    MQTTMessage as MQTTMessage,
)
from external_server.logs import CarLogger as _CarLogger
from external_server.checkers.mqtt_session import MQTTSession
from paho.mqtt.enums import CallbackAPIVersion
from fleet_protocol_protobuf_files.ExternalProtocol_pb2 import (
    Connect as _Connect,
    ExternalClient as _ExternalClientMsg,
    ExternalServer as ExternalServerMsg,
    Status as _Status,
)
from external_server.models.events import EventType as _EventType, EventQueue as _EventQueue
from external_server.models.exceptions import MQTTCommunicationError, CouldNotConnectToBroker

# maximum number of messages in outgoing queue
# value reasoning: external server can handle approximatelly 20 devices
_MAX_QUEUED_MESSAGES = 20
# value reasoning: keepalive is half of the default timeout in Fleet Protocol (30 s)
_KEEPALIVE = 15
# Quality of Service used by Mqtt client
_QOS = 1
# Time in seconds to wait for the client to be connected
_MQTT_CONNECTION_STATE_UPDATE_TIMEOUT = 1.0
_ID_LENGTH = 20


ClientConnectionState = _ConnectionState


_logger = _CarLogger()


def create_mqtt_client(car: str) -> _Client:
    try:
        client_id = "".join(secrets.choice(string.ascii_letters) for _ in range(_ID_LENGTH))
        client = _Client(
            callback_api_version=CallbackAPIVersion.VERSION2,
            client_id=client_id,
            protocol=mqtt.MQTTv311,
            reconnect_on_failure=True,
        )
        client.max_queued_messages_set(_MAX_QUEUED_MESSAGES)
        return client
    except Exception as e:
        _logger.error(f"Failed to create MQTT client: {e}", car)
        raise


def mqtt_error_from_code(code: int) -> str:
    """Return the error message based on the given code.

    If the code is not recognized, an empty string is returned.
    """
    enum_val = _MQTTErrorCode._value2member_map_.get(code)
    if enum_val is None:
        return "Unknown error code"
    return "(from MQTT error code): " + _error_string(enum_val).rstrip(".")


class MQTTClientAdapter:
    """Class binding together a MQTT client and queues for storing received messages and events.

    Enables to set up in advance the timeout for getting messages from the queues and connection
    parameters for the MQTT client.
    """

    _EXTERNAL_SERVER_SUFFIX = "external_server"
    _MODULE_GATEWAY_SUFFIX = "module_gateway"

    def __init__(
        self,
        company: str,
        car: str,
        timeout: float,
        broker_host: str,
        port: int,
        event_queue: Optional[_EventQueue] = None,
        mqtt_timeout: float = 0.5,
    ) -> None:
        self._publish_topic = self.get_publish_topic(company, car)
        self._subscribe_topic = self.get_subscribe_topic(company, car)
        self._received_msgs: Queue[_ExternalClientMsg] = Queue()
        self._mqtt_client = create_mqtt_client(car)
        self._event_queue = event_queue or _EventQueue(car=car)
        self._timeout = timeout
        self._keepalive = _KEEPALIVE
        self._broker_host = broker_host
        self._broker_port = port
        self._session = MQTTSession(mqtt_timeout, self._event_queue, car)
        self._set_up_callbacks()
        self._car = car

    @property
    def broker_address(self) -> str:
        """The address of the MQTT broker."""
        return f"{self._broker_host}:{self._broker_port}"

    @property
    def client(self) -> _Client:
        """The MQTT client instance."""
        return self._mqtt_client

    @property
    def is_connected(self) -> bool:
        """Whether the MQTT client is connected to the broker with its loop started."""
        return self._mqtt_client.is_connected()

    @property
    def is_running(self) -> bool:
        """Whether the MQTT client's loop is running."""
        return self._mqtt_client._thread is not None and self._mqtt_client._thread.is_alive()

    @property
    def publish_topic(self) -> str:
        """The topic the MQTT client is publishing to."""
        return self._publish_topic

    @property
    def received_messages(self) -> Queue[_ExternalClientMsg]:
        """A queue to store received messages."""
        return self._received_msgs

    @property
    def session(self) -> MQTTSession:
        """The session of the MQTT client."""
        return self._session

    @property
    def subscribe_topic(self) -> str:
        """The topic the MQTT client is subscribed to."""
        return self._subscribe_topic

    @property
    def thread(self) -> threading.Thread | None:
        """The thread of the MQTT client."""
        return self._mqtt_client._thread

    @property
    def timeout(self) -> Optional[float]:
        """The timeout for getting messages from the received messages queue."""
        return self._timeout

    def connect(self) -> int:
        """Connect to the MQTT broker using host and port provided during initialization."""
        self._connect_to_broker()
        code = self._start_communication()
        return self._handle_response_code_of_setting_up_conn_to_broker(code)

    def disconnect(self) -> None:
        """Disconnect from the MQTT broker. No action is taken if the MQTT client is already disconnected."""
        code = self._mqtt_client.disconnect()
        broker_str = f"MQTT broker on address '{self.broker_address}'"
        if code == mqtt.MQTT_ERR_SUCCESS:
            _logger.info(f"Communication with {broker_str} is stopped.", self._car)
        elif code == mqtt.MQTT_ERR_NO_CONN and not self._mqtt_client.is_connected():
            _logger.info(f"Communication with {broker_str} is already stopped.", self._car)
        elif not self._mqtt_client.is_connected():
            _logger.warning(
                f"Communication with {broker_str} is stopped. Error: {mqtt_error_from_code(code)}",
                self._car,
            )
        else:  # the client is still runnning and connected to the broker
            _logger.error(
                f"Failed to disconnect client from {broker_str}. Error: {mqtt_error_from_code(code)}",
                self._car,
            )
        self._stop_client_loop()

    def _handle_response_code_of_setting_up_conn_to_broker(self, code: int) -> int:
        try:
            if code == mqtt.MQTT_ERR_SUCCESS:
                return code
            error = mqtt_error_from_code(code)
            if self._mqtt_client.is_connected():
                _logger.warning(
                    "External server MQTT connection - communication between client and broker "
                    f"'{self.broker_address}' is established with error message: {error}",
                    self._car,
                )
                return code
            else:
                raise CouldNotConnectToBroker(error)
        except Exception as e:
            raise CouldNotConnectToBroker from e

    def _connect_to_broker(self) -> None:
        """Create a connection to the MQTT broker. This is required before starting communication loop of the MQTT client.

        Raise `CouldNotConnectToBroker` if the connection is not estabilished or if MQTT client returns code other that MQTT_ERR_SUCCESS.
        """
        try:
            code = self._mqtt_client.connect(
                host=self._broker_host, port=self._broker_port, keepalive=_KEEPALIVE
            )
            if code == mqtt.MQTT_ERR_SUCCESS:
                _logger.info(f"Connected to MQTT broker on {self.broker_address}.", self._car)
            else:
                error = mqtt_error_from_code(code)
                raise CouldNotConnectToBroker(error)
            assert code == mqtt.MQTT_ERR_SUCCESS
        except Exception as e:
            raise CouldNotConnectToBroker(f"Could not connect to the MQTT broker. {e}") from e

    def get_connect_message(self) -> _Connect | None:
        """Get expected connect message from MQTT client.

        Return None if the message is not received or is not a connect message.
        """
        return self._get_message_field("connect")

    def get_status(self) -> _Status | None:
        """Get expected status message from MQTT client.

        Return None if the message is not received or is not a status message.
        """
        return self._get_message_field("status")

    def _get_message_field(self, field_name: str) -> Optional[Any]:
        """Get an expected message and return the field with the given name.

        If the message is not received or does not contain the field, `None` is returned.
        """
        msg = self._get_message()
        if msg is None:
            _logger.info(f"{field_name.capitalize()} message has not been received.", self._car)
            return None
        elif msg.HasField(field_name):
            return getattr(msg, field_name)
        else:
            _logger.info(
                f"Received message is not a {field_name}. "
                f"Message type is {self._ext_client_message_type(msg)}",
                self._car,
            )
            return None

    def _ext_client_message_type(self, msg: _ExternalClientMsg) -> str:
        if msg.HasField("connect"):
            return "connect"
        if msg.HasField("status"):
            return "status"
        if msg.HasField("commandResponse"):
            return "command response"
        return "unknown"

    def publish(self, msg: ExternalServerMsg, log_msg: str = "") -> None:
        """Publish a message to the MQTT broker."""
        payload = msg.SerializeToString()
        code = self._mqtt_client.publish(self._publish_topic, payload, qos=_QOS).rc
        if code == mqtt.MQTT_ERR_SUCCESS:
            if log_msg:
                _logger.info(log_msg, self._car)
        else:
            msg = f"Failed to publish message. {mqtt_error_from_code(code)}."
            _logger.warning(msg, self._car)
            raise MQTTCommunicationError(msg)

    def _stop_client_loop(self) -> int:
        """Stop the MQTT client's traffic-processing loop. If the loop is not running, no action is taken."""
        if self._mqtt_client._thread is not None and self._mqtt_client._thread.is_alive():
            code = self._mqtt_client.loop_stop()
            return code
        else:
            return mqtt.MQTT_ERR_NO_CONN

    def set_tls(self, ca_certs: str, certfile: str, keyfile: str) -> None:
        """Set the TLS configuration for the MQTT client.

        `ca_certs` - path to the CA certificates file.
        `certfile` - path to the client certificate file.
        `keyfile` - path to the client private key file.

        All the files must exist, otherwise an exception is raised.
        """
        self._check_tls_files_existence(ca_certs, certfile, keyfile)
        self._mqtt_client.tls_set(
            ca_certs=ca_certs,
            certfile=certfile,
            keyfile=keyfile,
            tls_version=ssl.PROTOCOL_TLS_CLIENT,
        )

    def _check_tls_files_existence(self, ca_certs: str, certfile: str, keyfile: str) -> None:
        """Raise an exception if any of the given files does not exist."""
        if not os.path.isfile(ca_certs):
            raise FileNotFoundError(ca_certs)
        if not os.path.isfile(certfile):
            raise FileNotFoundError(certfile)
        if not os.path.isfile(keyfile):
            raise FileNotFoundError(keyfile)

    def _get_message(self, ignore_timeout: bool = False) -> _ExternalClientMsg | None:
        """Returns message from MQTTClient.

        If `ignore_timeout` is `False`(default), the function blocks until message is
        available or timeout is reached (then `None` is returned).

        If `ignore_timeout` is set to `True`, the function will return only if a message is
        available.
        """
        t = None if ignore_timeout else self._timeout
        try:
            message = self._received_msgs.get(block=True, timeout=t)
            return message
        except Empty:
            return None

    def _start_communication(self) -> int:
        """Set up the MQTT client traffic processing (callbacks and subscriptions) and ensure the traffic processing loop is running."""
        self._set_up_callbacks()
        code = self._start_client_loop()
        connection = self._wait_for_connection(_MQTT_CONNECTION_STATE_UPDATE_TIMEOUT)
        if connection:
            _logger.debug(
                f"\nListening on topic: {self._subscribe_topic}"
                f"\nPublishing on topic: {self._publish_topic}",
                self._car,
            )
        return code

    def _log_connection_result(self, code: int) -> None:
        address = self.broker_address
        if code == mqtt.MQTT_ERR_SUCCESS:
            _logger.info(f"Connected to a broker on '{address}'.", self._car)
        else:
            _logger.info(
                f"Connecting to a broker on '{address}' failed. {mqtt_error_from_code(code)}",
                self._car,
            )

    def _on_connect(self, client: _Client, data: Any, flags: Any, rc, properties: Any) -> None:
        """Callback function for handling connection events.

        Args:
        - `client` The MQTT client instance.
        - `data` The user data associated with the client.
        - `flags` Response flags sent by the broker.
        - `rc` The connection result code indicating success or failure.
        - `properties` The properties associated with the connection event.
        """
        self._mqtt_client.subscribe(self._subscribe_topic, qos=_QOS)
        self._log_connection_result(rc)

    def _on_disconnect(self, client: _Client, data: Any, flags: Any, rc, properties: Any) -> None:
        """Callback function for handling disconnection events.

        Args:
        - `client` The MQTT client instance.
        - `data` The user data associated with the client.
        - `rc (int)` The return code indicating the reason for disconnection.
        - `properties` The properties associated with the disconnection event.
        """
        self._event_queue.add(event_type=_EventType.MQTT_BROKER_DISCONNECTED)

    def _on_message(self, client: _Client, data: Any, message: MQTTMessage) -> None:
        """Callback function for handling incoming messages.

        The message is added to the received messages queue, if the topic matches the subscribe topic,
        and an event is added to the event queue.

        Args:
        - `client` The MQTT client instance.
        - `data` The user data associated with the client.
        - `message` (mqtt.MQTTMessage): The received MQTT message.
        """
        try:
            if message.topic == self._subscribe_topic:
                msg = _ExternalClientMsg.FromString(message.payload)
                self._received_msgs.put(msg)
                self._event_queue.add(event_type=_EventType.CAR_MESSAGE_AVAILABLE)
        except Exception as e:  # pragma: no cover
            _logger.error(
                f"MQTT on message callback: Failed to parse the received message. {e}", self._car
            )

    def _set_up_callbacks(self) -> None:
        self._mqtt_client.on_connect = self._on_connect
        self._mqtt_client.on_disconnect = self._on_disconnect
        self._mqtt_client.on_message = self._on_message

    def _start_client_loop(self) -> int:
        """Start the MQTT client traffic-processing loop. If the loop is already running it is
        stopped first and then started again."""
        if self._mqtt_client._thread is not None:
            _logger.warning(
                "Attempted to start MQTT client traffic-processing loop, but it is already running. "
                "Stopping the current loop, starting a new one.",
                self._car,
            )
            if self._mqtt_client._thread.is_alive():
                self._mqtt_client.loop_stop()
            self._mqtt_client._thread = None
        return self._mqtt_client.loop_start()

    def _wait_for_connection(self, timeout: float) -> bool:  # pragma: no cover
        """Wait for the connection to be established."""
        start = time.monotonic()
        timeout_s = max(timeout, 0.0)  # timeout in seconds
        while time.monotonic() - start < timeout_s:
            if self.is_connected:
                return True
            time.sleep(0.01)
        return False

    @staticmethod
    def get_subscribe_topic(company: str, car: str) -> str:
        """Return the topic the MQTT client is subscribed to."""
        return f"{company}/{car}/{MQTTClientAdapter._MODULE_GATEWAY_SUFFIX}"

    @staticmethod
    def get_publish_topic(company: str, car: str) -> str:
        """Return the topic the MQTT client is publishing to."""
        return f"{company}/{car}/{MQTTClientAdapter._EXTERNAL_SERVER_SUFFIX}"
