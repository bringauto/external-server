import string
import random
import time

import paho.mqtt.client as mqtt

from external_server.utils import check_file_exists


class Server:

    def __init__(self, ip: str, port: int) -> None:
        self.running = True
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
            self.mqtt_client.subscribe("#", qos=2)
        self.mqtt_client.on_disconnect = lambda client, userdata, rc, properties:\
            print("Unexpected disconnection.") if rc != 0 else print('Disconnected')
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
        print('Disconnect')

    def _on_message(self, client, userdata, message) -> None:
        print(message.topic)
