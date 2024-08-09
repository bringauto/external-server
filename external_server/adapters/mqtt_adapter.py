import logging.config
import json
import random
import string
from queue import Queue, Empty
import sys
import ssl
from typing import Optional, Any
import time
import os

sys.path.append("lib/fleet-protocol/protobuf/compiled/python")

import paho.mqtt.client as mqtt
from paho.mqtt.client import (
    Client as _Client,
    _ConnectionState as _ConnectionState,
    error_string as _error_string,
    MQTTErrorCode as _MQTTErrorCode,
    MQTTMessage as MQTTMessage,
)
from paho.mqtt.enums import CallbackAPIVersion

from ExternalProtocol_pb2 import (  # type: ignore
    Connect as _Connect,
    ExternalClient as _ExternalClientMsg,
    ExternalServer as _ExternalServerMsg,
    Status as _Status,
)
from external_server.models.events import EventQueueSingleton, EventType


# maximum number of messages in outgoing queue
# value reasoning: external server can handle approximatelly 20 devices
_MAX_QUEUED_MESSAGES = 20
# value reasoning: keepalive is half of the default timeout in Fleet Protocol (30 s)
_KEEPALIVE = 15
# Quality of Service used by Mqtt client
_QOS = 1
# Time in seconds to wait for the client to be connected
_MQTT_CONNECTION_STATE_UPDATE_TIMEOUT = 1.0


ClientConnectionState = _ConnectionState


_logger = logging.getLogger(__name__)
with open("./config/logging.json", "r") as f:
    logging.config.dictConfig(json.load(f))


def create_mqtt_client() -> _Client:
    client_id = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    client = _Client(
        callback_api_version=CallbackAPIVersion.VERSION2,
        client_id=client_id,
        protocol=mqtt.MQTTv311,
        reconnect_on_failure=True,
    )
    client.max_queued_messages_set(_MAX_QUEUED_MESSAGES)
    return client


def mqtt_error_from_code(code: int) -> str:
    """Return the error message based on the given code.

    If the code is not recognized, an empty string is returned.
    """
    try:
        enum_val = _MQTTErrorCode._value2member_map_[code]
        return _error_string(enum_val)  # type: ignore
    except:
        return ""


class MQTTClientAdapter:
    """Class binding together a MQTT client and queues for storing received messages and events.

    Enables to set up in advance the timeout for getting messages from the queues and connection
    parameters for the MQTT client.
    """

    _EXTERNAL_SERVER_SUFFIX = "external_server"
    _MODULE_GATEWAY_SUFFIX = "module_gateway"

    def __init__(self, company: str, car: str, timeout: float, broker_host: str, port: int) -> None:
        self._publish_topic = f"{company}/{car}/{MQTTClientAdapter._EXTERNAL_SERVER_SUFFIX}"
        self._subscribe_topic = f"{company}/{car}/{MQTTClientAdapter._MODULE_GATEWAY_SUFFIX}"
        self._received_msgs: Queue[_ExternalClientMsg] = Queue()
        self._mqtt_client = create_mqtt_client()
        self._event_queue = EventQueueSingleton()
        self._timeout = timeout
        self._keepalive = _KEEPALIVE
        self._broker_host = broker_host
        self._broker_port = port
        self._set_up_callbacks()

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
    def state(self) -> ClientConnectionState:
        """The state of the MQTT client."""
        return self._mqtt_client._state

    @property
    def subscribe_topic(self) -> str:
        """The topic the MQTT client is subscribed to."""
        return self._subscribe_topic

    @property
    def timeout(self) -> Optional[float]:
        """The timeout for getting messages from the received messages queue."""
        return self._timeout

    def connect(self) -> Exception | None:
        """Connect to the MQTT broker.

        Returns an exception if raised, otherwise `None`.
        """
        try:
            code = self._mqtt_client.connect(self._broker_host, self._broker_port, _KEEPALIVE)
            if code == mqtt.MQTT_ERR_SUCCESS:
                self._set_up_callbacks()
                self._mqtt_client.subscribe(self._subscribe_topic, qos=_QOS)
                self._start_client_loop()
                self._wait_for_connection(_MQTT_CONNECTION_STATE_UPDATE_TIMEOUT)
            else:
                _logger.error(
                    f"Failed to connect to broker: {self._broker_host}:{self._broker_port}. "
                    f"{mqtt_error_from_code(code)}"
                )
            return None
        except ConnectionRefusedError as e:
            self.stop()
            _logger.error(
                f"Cannot connect to a broker {self._broker_host}:{self._broker_port}: {e}"
            )
            return e
        except Exception as e:  # pragma: no cover
            _logger.error(f"Failed to connect to broker: {e}")
            return e

    def disconnect(self) -> None:
        """Disconnect from the MQTT broker."""
        if self._mqtt_client.is_connected():
            code = self._mqtt_client.disconnect()
            self.stop()
            if code == mqtt.MQTT_ERR_SUCCESS:
                _logger.info(f"Disconnected from MQTT broker: {self.broker_address}")
            else:
                _logger.error(
                    "Error when disconnecting from MQTT broker "
                    f"({self.broker_address}): {mqtt_error_from_code(code)}"
                )
        else:
            _logger.info(
                "Trying to disconnect from MQTT broker, but not connected. No action is taken."
            )

    def get_connect_message(self) -> _Connect | None:
        """"""
        msg = self._get_message()
        while msg is False:
            if self.is_connected:
                _logger.warning(
                    "Disconnect message from connecting client will be skipped. "
                    "Repeating message retrieval."
                )
            msg = self._get_message()
        if msg is None:
            if self.is_connected:
                _logger.error("Connect message has not been received.")
            return None
        elif not msg.HasField("connect"):
            if self.is_connected:
                _logger.error("Received message is not a connect message.")
            return None
        _logger.info("Connect message has been received.")
        return msg.connect

    def get_status(self) -> _Status | None:
        """Get expected status message from MQTT client.

        Raise an exception if the message is not received or is not a status message.
        """
        msg = self._get_message()
        if msg is None or msg == False:
            _logger.error("Expected valid status message has not been received.")
            return None
        if not msg.HasField("status"):
            _logger.error("Received message is not a status message.")
            return None
        return msg.status

    def publish(self, msg: _ExternalServerMsg, log_msg: str = "") -> None:
        """Publish a message to the MQTT broker."""
        payload = msg.SerializeToString()
        code = self._mqtt_client.publish(self._publish_topic, payload, qos=_QOS).rc
        if code == mqtt.MQTT_ERR_SUCCESS:
            if log_msg:
                _logger.info(log_msg)
        else:
            _logger.error(f"Failed to publish message. {mqtt_error_from_code(code)}.")

    def stop(self) -> None:
        """Stop the MQTT client's event loop. If the client is already stopped, no action
        is taken.
        """
        cli = self._mqtt_client
        if cli._thread and cli._thread.is_alive():
            code = self._mqtt_client.loop_stop()
            if code == mqtt.MQTT_ERR_SUCCESS:
                _logger.debug("Stopped MQTT client's loop.")
            else:
                _logger.error(f"Failed to stop MQTT client's loop: {mqtt_error_from_code(code)}")
        else:
            _logger.debug("Trying to stop MQTT client's event loop, but it is already stopped.")

    def tls_set(self, ca_certs: str, certfile: str, keyfile: str) -> None:
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

    def _log_connection_result(self, code: int) -> None:
        address = self.broker_address
        if code == mqtt.MQTT_ERR_SUCCESS:
            _logger.info(f"Connected to a MQTT broker ({address}).")
        else:
            _logger.error(f"Cannot connect to broker ({address})." f"{mqtt_error_from_code(code)}")

    def _on_connect(self, client: _Client, data, flags, rc, properties) -> None:
        """Callback function for handling connection events.

        Args:
        - `client` The MQTT client instance.
        - `data` The user data associated with the client.
        - `flags`
        - `rc` The return code indicating the reason for disconnection.
        - `properties` The properties associated with the disconnection event.
        """
        self._log_connection_result(rc)

    def _on_disconnect(self, client: _Client, data: Any, flags: Any, rc, properties) -> None:
        """Callback function for handling disconnection events.

        Args:
        - `client` The MQTT client instance.
        - `data` The user data associated with the client.
        - `rc (int)` The return code indicating the reason for disconnection.
        - `properties` The properties associated with the disconnection event.
        """
        try:
            self._received_msgs.put(False)
            self._event_queue.add(event_type=EventType.MQTT_BROKER_DISCONNECTED)
        except:  # pragma: no cover
            _logger.error("MQTT on disconnect callback: Failed to disconnect from the broker")

    def _on_message(self, client: _Client, data, message: MQTTMessage) -> None:
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
                msg = _ExternalClientMsg().FromString(message.payload)
                self._received_msgs.put(msg)
                self._event_queue.add(event_type=EventType.CAR_MESSAGE_AVAILABLE)
        except:  # pragma: no cover
            _logger.error("MQTT on message callback: Failed to parse the received message")

    def _set_up_callbacks(self) -> None:
        self._mqtt_client.on_connect = self._on_connect
        self._mqtt_client.on_disconnect = self._on_disconnect
        self._mqtt_client.on_message = self._on_message

    def _start_client_loop(self) -> None:
        code = self._mqtt_client.loop_start()
        if code == mqtt.MQTT_ERR_SUCCESS:
            _logger.debug("Started MQTT client's event loop")
        else:
            _logger.error(f"Failed to start MQTT client's event loop: {mqtt_error_from_code(code)}")

    def _wait_for_connection(self, timeout: float) -> bool:  # pragma: no cover
        """Wait for the connection to be established.

        Returns `True` if the connection is established within the given timeout,
        otherwise `False`.

        `timeout` - the maximum time to wait for the connection to be established in seconds.
        """
        start = time.time()
        timeout_ms = max(timeout, 0) * 1000
        while time.time() - start < timeout_ms:
            if self.is_connected:
                return True
            time.sleep(0.01)
        return False
