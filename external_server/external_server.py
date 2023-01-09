import random
import string
import time

from external_server.utils import check_file_exists
from external_server.modules import CarAccessoryCreator
import external_server.protobuf.ExternalProtocol_pb2 as external_protocol

import paho.mqtt.client as mqtt


class ExternalServer:

    def __init__(self, ip: str, port: int) -> None:
        self.ip = ip
        self.port = port

    def init_mqtt_client(self) -> None:
        self.mqtt_client = mqtt.Client(
            client_id=''.join(random.choices(
                string.ascii_uppercase + string.digits, k=20)),
            clean_session=None,
            userdata=None,
            protocol=mqtt.MQTTv5,
            transport='tcp')
        self.mqtt_client.on_connect = lambda client, userdata, flags, rc, properties:\
            client.subscribe('to-server/CAR1', qos=2)
        self.mqtt_client.on_disconnect = lambda client, userdata, rc, properties:\
            print("Unexpected disconnection.") if rc != 0 else print('Disconnect')
        self.mqtt_client.on_message = self._on_message

    def set_tls(self, ca_certs: str, certfile: str,
                keyfile: str) -> None:
        if not check_file_exists(ca_certs):
            raise FileNotFoundError(ca_certs)
        if not check_file_exists(certfile):
            raise FileNotFoundError(certfile)
        if not check_file_exists(keyfile):
            raise FileNotFoundError(keyfile)
        self.mqtt_client.tls_set(
            ca_certs=ca_certs,
            certfile=certfile,
            keyfile=keyfile
        )
        self.mqtt_client.tls_insecure_set(True)

    def start(self) -> None:
        self.running = True
        while self.running:
            try:
                self.mqtt_client.connect(
                    self.ip, port=self.port, keepalive=60
                )
                print("Connected to MQTT broker")
                self.mqtt_client.loop_forever()
            except ConnectionRefusedError:
                print("Unable to connect, trying again")
                time.sleep(1)

    def stop(self) -> None:
        self.running = False
        self.mqtt_client.disconnect()

    def _on_message(self, client: mqtt.Client, userdata, message: mqtt.MQTTMessage) -> None:
        message_external_client = external_protocol.ExternalClient().FromString(message.payload)
        message_external_server = external_protocol.ExternalServer()
        car_accessory_creator = CarAccessoryCreator()
        session_id = message_external_client.connect.sessionId
        if message_external_client.HasField("connect"):
            print(f'Received connect message on topic: {message.topic}')
            connect_response = car_accessory_creator.create_connect_response(session_id)
            message_external_server.connectReponse.CopyFrom(connect_response)
            client.publish('to-client/CAR1', message_external_server.SerializeToString())
        elif message_external_client.HasField("status"):
            print(f'Received status message on topic: {message.topic}')
            status_response = car_accessory_creator.create_status_response(
                session_id,
                message_external_client.status.messageCounter
            )
            message_external_server.statusResponse.CopyFrom(status_response)
            client.publish('to-client/CAR1', message_external_server.SerializeToString())

            message_external_server = external_protocol.ExternalServer()
            message_external_server.command.CopyFrom(
                car_accessory_creator.create_command(session_id, message_external_client.status.deviceStatus.statusData)
            )
            client.publish('to-client/CAR1', message_external_server.SerializeToString())
        elif message_external_client.HasField("commandResponse"):
            print(f'Received command response on topic: {message.topic}')
