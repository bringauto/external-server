import logging
import time
from collections import defaultdict
from queue import Empty, Queue

import external_server.protobuf.ExternalProtocol_pb2 as external_protocol
from external_server.exceptions import ConnectSequenceException
from external_server.modules import CarAccessoryCreator, MissionCreator
from external_server.modules.module_type import ModuleType
from external_server.mqtt_client import MqttClient
from external_server.utils import check_file_exists


class ExternalServer:

    TIMEOUT = 30

    def __init__(self, ip: str, port: int) -> None:
        self.ip = ip
        self.port = port
        # TODO create own class for these two
        self.command_responses = Queue()
        self._command_counter = 0
        self.connected_devices = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: False)))
        self.message_creator = {
            ModuleType.MISSION_MODULE.value: MissionCreator(),
            ModuleType.CAR_ACCESSORY_MODULE.value: CarAccessoryCreator()
        }
        self.mqtt_client = MqttClient()

    @property
    def command_counter(self):
        self._command_counter += 1
        return self._command_counter

    def set_tls(self, ca_certs: str, certfile: str, keyfile: str) -> None:
        if not check_file_exists(ca_certs):
            raise FileNotFoundError(ca_certs)
        if not check_file_exists(certfile):
            raise FileNotFoundError(certfile)
        if not check_file_exists(keyfile):
            raise FileNotFoundError(keyfile)
        self.mqtt_client.set_tls(ca_certs, certfile, keyfile)

    def start(self) -> None:
        self.mqtt_client.init_mqtt_client()
        while True:
            try:
                if not self.mqtt_client.is_connected:
                    self.mqtt_client.connect(self.ip, self.port)
                logging.info("Server connected to MQTT broker")
                self.mqtt_client.start()
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
        devices_num = self._init_seq_connect()
        received_statuses = self._init_seq_status(devices_num)
        self._init_seq_command(devices_num, received_statuses)
        logging.info('Connect sequence has been succesfully finished')

    def _init_seq_connect(self) -> int:
        received_msg = self.mqtt_client.get()
        if not received_msg.HasField("connect"):
            logging.error("Connect sequence: Connect message has been expected")
            raise ConnectSequenceException()
        logging.info("Connect sequence: Connect message has been received")

        devices = received_msg.connect.devices
        for device in devices:
            self.connected_devices[device.module][device.deviceType][device.deviceRole] = True

        sent_msg = self._create_connect_response(
            received_msg.connect.sessionId,
            external_protocol.ConnectResponse.Type.OK
        )
        self.mqtt_client.publish(sent_msg)
        logging.info("Connect sequence: Connect message has been sent")
        return len(devices)

    def _init_seq_status(self, devices_num: int) -> Queue:
        received_statuses = Queue()
        for i in range(devices_num):
            status_msg = self.mqtt_client.get(timeout=ExternalServer.TIMEOUT)
            # TODO add it to the function probably
            if not status_msg.HasField("status"):
                logging.error("Connect sequence: Status message has been expected")
                raise ConnectSequenceException()

            device = status_msg.status.deviceStatus.device
            if not self._check_device_is_connected(device):
                logging.error(f"Recieved status from not connected device, unique identificator:\
                                {device.module}/{device.deviceType}/{device.deviceRole}")
                raise ConnectSequenceException()

            if not self._check_status_device_state(status_msg, external_protocol.Status.DeviceState.CONNECTING):
                logging.error(f"Status device state is different. actual: {status_msg.status.deviceState}\
                                expected: {external_protocol.Status.DeviceState.CONNECTING}")
                raise ConnectSequenceException()
            logging.info(f"Connect sequence: Status message has been received {i}")
            received_statuses.put(status_msg)
            sent_msg = self._create_status_response(status_msg)
            self.mqtt_client.publish(sent_msg)
            logging.info(f"Connect sequence: Status response message has been sent {i}")
        return received_statuses

    def _init_seq_command(self, devices_num: int, received_statuses: Queue) -> None:
        for i in range(devices_num):
            status_message = received_statuses.get()
            sent_msg = self._create_command(status_message)
            self.mqtt_client.publish(sent_msg)
            logging.info(f"Connect sequence: Command message has been sent {i}")

        for i in range(devices_num):
            received_msg = self.mqtt_client.get(timeout=ExternalServer.TIMEOUT)
            if not received_msg.HasField("commandResponse"):
                logging.error("Connect sequence: Command response message has been expected")
                raise ConnectSequenceException()
            self._check_command_response_order(received_msg.commandResponse.messageCounter)
            logging.info(f"Connect sequence: Command response message has been received {i}")

    def _normal_communication(self):
        while self.mqtt_client.is_connected:
            received_msg = self.mqtt_client.get(timeout=ExternalServer.TIMEOUT)
            if isinstance(received_msg, bool):
                logging.error("Unexpected disconnection.")
                self.mqtt_client.is_connected = False
                break

            if received_msg.HasField("connect"):
                logging.warning("Received unexpected Connect message")
                sent_msg = self._create_connect_response(
                    received_msg.connect.sessionId,
                    external_protocol.ConnectResponse.Type.ALREADY_LOGGED
                )
                self.mqtt_client.publish(sent_msg)
                logging.warning("Sending Connect response message")

            elif received_msg.HasField("status"):
                logging.info("Received Status message message")
                # TODO remove duplicity
                match received_msg.status.deviceState:
                    case external_protocol.Status.DeviceState.RUNNING:
                        device = received_msg.status.deviceStatus.device
                        if not self._check_device_is_connected(device):
                            logging.error(f'Device {device.module}/{device.deviceType}/{device.deviceRole} \
                                            is not connected')

                        sent_msg = self._create_status_response(received_msg)
                        self.mqtt_client.publish(sent_msg)
                        logging.info("Sending Status response message")

                        sent_msg = self._create_command(received_msg)
                        self.mqtt_client.publish(sent_msg)
                        logging.info("Sending Command message")

                    case external_protocol.Status.DeviceState.CONNECTING:
                        device = received_msg.status.deviceStatus.device
                        if self._check_device_is_connected(device):
                            logging.error(f'Device {device.module}/{device.deviceType}/{device.deviceRole} \
                                            is already connected')

                        sent_msg = self._create_status_response(received_msg)
                        self.mqtt_client.publish(sent_msg)
                        logging.info("Sending Status response message")

                        sent_msg = self._create_command(received_msg)
                        self.mqtt_client.publish(sent_msg)
                        logging.info("Sending Command message")

                        device = received_msg.status.deviceStatus.device
                        self.connected_devices[device.module][device.deviceType][device.deviceRole] = True

                    case external_protocol.Status.DeviceState.DISCONNECT:
                        device = received_msg.status.deviceStatus.device
                        if not self._check_device_is_connected(device):
                            logging.error(f'Device {device.module}/{device.deviceType}/{device.deviceRole} \
                                            is not connected')

                        sent_msg = self._create_status_response(received_msg)
                        self.mqtt_client.publish(sent_msg)
                        device = received_msg.status.deviceStatus.device
                        self.connected_devices[device.module][device.deviceType][device.deviceRole] = False
                        logging.info("Sending Status response message")

            elif received_msg.HasField("commandResponse"):
                logging.info("Received Command response message")
                # throws exceptions and this behaviour is not needed, but probably it is
                self._check_command_response_order(received_msg.commandResponse.messageCounter)

    def stop(self) -> None:
        logging.info('Server stopped')
        self.mqtt_client.stop()

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

    def _check_device_is_connected(self, device) -> bool:
        return True if self.connected_devices[device.module][device.deviceType][device.deviceRole] else False

    def _check_status_device_state(self, status: external_protocol.ExternalClient,
                                   device_state: external_protocol.Status.DeviceState) -> bool:
        return True if status.status.deviceState == device_state else False
