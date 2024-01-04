import pytest
from unittest.mock import MagicMock
import sys

sys.path.append("lib/fleet-protocol/protobuf/compiled/python")

from external_server.mqtt_client import MqttClient
import ExternalProtocol_pb2 as external_protocol


@pytest.fixture
def mqtt_client():
    return MqttClient("company_name", "car_name")


def test_init(mqtt_client):
    assert mqtt_client.publish_topic == "company_name/car_name/external_server"
    assert mqtt_client.is_connected is False


def test_set_tls_with_non_existing_certificates(mqtt_client):
    ca_certs = "ca.crt"
    certfile = "client.crt"
    keyfile = "client.key"

    with pytest.raises(FileNotFoundError) as _:
        mqtt_client.set_tls(ca_certs, certfile, keyfile)


def test_init_connect(mqtt_client):
    mqtt_client.mqtt_client.connect = MagicMock()

    mqtt_client.init()
    mqtt_client.connect("127.0.0.1", 1883)

    mqtt_client.mqtt_client.connect.assert_called_once()


def test_connect_to_non_existent_broker_fixed_fixed(mqtt_client):
    import socket

    with pytest.raises(socket.gaierror):
        mqtt_client.connect("non_existent_broker", 1883)


def test_publish(mqtt_client):
    mqtt_client.mqtt_client.publish = MagicMock()

    sent_msg = external_protocol.ExternalServer()
    sent_msg.connectResponse.sessionId = "session_id"
    sent_msg.connectResponse.type = external_protocol.ConnectResponse.Type.OK

    mqtt_client.init()
    try:
        mqtt_client.connect("127.0.0.1", 1883)
    except ConnectionRefusedError:
        pytest.fail("Start mqtt broker to make this test work")
    mqtt_client.publish(sent_msg)

    mqtt_client.mqtt_client.publish.assert_called_once_with(
        mqtt_client.publish_topic, sent_msg.SerializeToString(), qos=0
    )


def test_stop(mqtt_client):
    mqtt_client.mqtt_client.loop_stop = MagicMock()

    mqtt_client.stop()

    mqtt_client.mqtt_client.loop_stop.assert_called_once()
    assert mqtt_client.is_connected is False
