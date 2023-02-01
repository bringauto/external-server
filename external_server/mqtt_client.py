
import logging
import random
import string
from queue import Queue

import paho.mqtt.client as mqtt

import external_server.protobuf.ExternalProtocol_pb2 as external_protocol


class MqttClient:

    def __init__(self) -> None:
        self.received_msgs: Queue[external_protocol.ExternalClient] = Queue()
        self.mqtt_client = mqtt.Client(
            client_id=''.join(random.choices(string.ascii_uppercase + string.digits, k=20)),
            protocol=mqtt.MQTTv5
        )
        self._is_connected = False

    def set_tls(self, ca_certs: str, certfile: str, keyfile: str) -> None:
        self.mqtt_client.tls_set(
            ca_certs=ca_certs,
            certfile=certfile,
            keyfile=keyfile
        )
        self.mqtt_client.tls_insecure_set(True)

    def init_mqtt_client(self) -> None:
        self.mqtt_client.on_connect = lambda client, _userdata, _flags, _rc, _properties:\
            client.subscribe('to-server/CAR1', qos=0)
        self.mqtt_client.on_disconnect = lambda _client, _userdata, rc, _properties:\
            self.received_msgs.put(False) if rc != 0 else logging.info("Disconnect")
        self.mqtt_client.on_message = self._on_message

    def _on_message(self, _client: mqtt.Client, _userdata, message: mqtt.MQTTMessage) -> None:
        message_external_client = external_protocol.ExternalClient().FromString(message.payload)
        self.received_msgs.put(message_external_client)

    def connect(self, ip: str, port: int) -> None:
        self.mqtt_client.connect(ip, port=port, keepalive=60, clean_start=True)
        self._is_connected = True
        logging.info("Server connected to MQTT broker")

    def start(self) -> None:
        self.mqtt_client.loop_start()

    def stop(self) -> None:
        self.mqtt_client.loop_stop()
        self._is_connected = False

    def publish(self, msg: external_protocol.ExternalServer) -> None:
        self.mqtt_client.publish('to-client/CAR1', msg.SerializeToString(), qos=0)

    def get(self, timeout: int | None = None) -> external_protocol.ExternalClient:
        return self.received_msgs.get(block=True, timeout=timeout)

    @property
    def is_connected(self) -> bool:
        return self._is_connected
