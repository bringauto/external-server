import random
import string
import time
import logging
from queue import Queue, Empty

import paho.mqtt.client as mqtt

from external_server.exceptions import ConnectSequenceException
from external_server.utils import check_file_exists
from external_server.modules import (
    CarAccessoryCreator,
    MissionCreator
)
from external_server.modules.module_type import ModuleType
import external_server.protobuf.ExternalProtocol_pb2 as external_protocol


class ExternalServer:

    TIMEOUT = 30

    def __init__(self, ip: str, port: int) -> None:
        self.ip = ip
        self.port = port
        self.received_msgs = Queue()
        self.command_responses = Queue()
        self._command_counter = 0
        self.message_creator = {
            ModuleType.MISSION_MODULE.value: MissionCreator(),
            ModuleType.CAR_ACCESSORY_MODULE.value: CarAccessoryCreator()
        }
        self.mqtt_client = mqtt.Client(
            client_id=''.join(random.choices(string.ascii_uppercase + string.digits, k=20)),
            clean_session=None,
            userdata=None,
            protocol=mqtt.MQTTv5,
            transport='tcp'
        )
        self.connected = False

    @property
    def command_counter(self):
        self._command_counter += 1
        return self._command_counter

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

    def init_mqtt_client(self) -> None:
        self.mqtt_client.on_connect = lambda client, userdata, flags, rc, properties:\
            client.subscribe('to-server/CAR1', qos=2)
        self.mqtt_client.on_disconnect = lambda client, userdata, rc, properties:\
            self.received_msgs.put(False) if rc != 0 else logging.info("Disconnect")
        self.mqtt_client.on_message = self._on_message

    def _on_message(self, _client: mqtt.Client, _userdata, message: mqtt.MQTTMessage) -> None:
        message_external_client = external_protocol.ExternalClient().FromString(message.payload)
        self.received_msgs.put(message_external_client)

    def start(self) -> None:
        while True:
            try:
                if not self.connected:
                    self.mqtt_client.connect(self.ip, port=self.port, keepalive=60)
                    self.connected = True
                logging.info("Server connected to MQTT broker")
                self.mqtt_client.loop_start()
                self._init_sequence()
                self._normal_communication()
            except ConnectSequenceException:
                logging.error("Connect sequence failed")
            except ConnectionRefusedError:
                logging.error("Unable to connect, trying again")
            except Empty:
                logging.error("Client timed out")
            finally:
                time.sleep(0.5)

    def _init_sequence(self) -> None:
        devices_num = self._init_connect()
        received_statuses = self._init_status(devices_num)
        self._init_command(devices_num, received_statuses)
        logging.info('Connect sequence has been succesfully finished')

    def _init_connect(self) -> int:
        received_msg = self.received_msgs.get(block=True)
        if not received_msg.HasField("connect"):
            logging.error("Connect sequence: Connect message has been expected")
            raise ConnectSequenceException()
        logging.info("Connect sequence: Connect message has been received")
        sent_msg = self._create_connect_response(
            received_msg.connect.sessionId,
            external_protocol.ConnectResponse.Type.OK
        )
        devices = received_msg.connect.devices

        self.mqtt_client.publish('to-client/CAR1', sent_msg.SerializeToString())
        logging.info("Connect sequence: Connect message has been sent")
        return len(devices)

    def _init_status(self, devices_num: int) -> Queue:
        received_statuses = Queue()
        for i in range(devices_num):
            status_msg = self.received_msgs.get(block=True, timeout=ExternalServer.TIMEOUT)
            if not status_msg.HasField("status"):
                logging.error("Connect sequence: Status message has been expected")
                raise ConnectSequenceException()
            logging.info(f"Connect sequence: Status message has been received {i}")
            received_statuses.put(status_msg)
            sent_msg = self._create_status_response(status_msg)
            self.mqtt_client.publish('to-client/CAR1', sent_msg.SerializeToString())
            logging.info(f"Connect sequence: Status response message has been sent {i}")
        return received_statuses

    def _init_command(self, devices_num: int, received_statuses: Queue) -> None:
        for i in range(devices_num):
            status_message = received_statuses.get()
            sent_msg = self._create_command(status_message)
            self.mqtt_client.publish('to-client/CAR1', sent_msg.SerializeToString())
            logging.info(f"Connect sequence: Command message has been sent {i}")

        for i in range(devices_num):
            received_msg = self.received_msgs.get(block=True, timeout=ExternalServer.TIMEOUT)
            if not received_msg.HasField("commandResponse"):
                logging.error("Connect sequence: Command response message has been expected")
                raise ConnectSequenceException()
            self._check_command_response_order(received_msg.commandResponse.messageCounter)
            logging.info(f"Connect sequence: Command response message has been received {i}")

    def _normal_communication(self):
        while self.connected:
            received_msg = self.received_msgs.get(block=True, timeout=ExternalServer.TIMEOUT)
            if isinstance(received_msg, bool):
                logging.error("Unexpected disconnection.")
                self.connected = False
                break

            if received_msg.HasField("connect"):
                logging.warning("Received unexpected Connect message")
                sent_msg = self._create_connect_response(
                    received_msg.connect.sessionId,
                    external_protocol.ConnectResponse.Type.ALREADY_LOGGED
                )
                self.mqtt_client.publish('to-client/CAR1', sent_msg.SerializeToString())
                logging.warning("Sending Connect response message")

            elif received_msg.HasField("status"):
                logging.info("Received Status message message")
                sent_msg = self._create_status_response(received_msg)
                self.mqtt_client.publish('to-client/CAR1', sent_msg.SerializeToString())
                logging.info("Sending Status response message")

                sent_msg = self._create_command(received_msg)
                self.mqtt_client.publish('to-client/CAR1', sent_msg.SerializeToString())
                logging.info("Sending Command message")

            elif received_msg.HasField("commandResponse"):
                logging.info("Received Command response message")
                self._check_command_response_order(received_msg.commandResponse.messageCounter)

    def stop(self) -> None:
        logging.info('Server stopped')
        self.mqtt_client.loop_stop()

    def _create_connect_response(self, session_id: str, connect_response_type: int) -> external_protocol.ExternalServer:
        connect_response = self.message_creator[ModuleType.MISSION_MODULE.value].create_connect_response(
            session_id,
            connect_response_type
        )
        sent_msg = external_protocol.ExternalServer()
        sent_msg.connectResponse.CopyFrom(connect_response)
        return sent_msg

    def _create_status_response(self, status_msg) -> external_protocol.ExternalServer:
        module = status_msg.status.deviceStatus.device.module
        if module not in self.message_creator:
            logging.error("Module is not supported")
            raise ConnectSequenceException()
        sent_msg = external_protocol.ExternalServer()
        sent_msg.statusResponse.CopyFrom(
            self.message_creator[module].create_status_response(
                status_msg.status.sessionId,
                status_msg.status.messageCounter
            )
        )
        return sent_msg

    def _create_command(self, status_msg) -> external_protocol.ExternalServer:
        module = status_msg.status.deviceStatus.device.module
        command_counter = self.command_counter
        sent_msg = external_protocol.ExternalServer()
        sent_msg.command.CopyFrom(
            self.message_creator[module].create_command(
                status_msg.status.sessionId,
                command_counter,
                status_msg.status.deviceStatus
            )
        )
        self.command_responses.put(command_counter)
        return sent_msg

    def _check_command_response_order(self, counter: int) -> None:
        if counter != self.command_responses.get():
            logging.error("Command response message has been recieved in bad order")
            logging.error("Closing connection")
            raise ConnectSequenceException()
