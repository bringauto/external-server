import unittest
from unittest.mock import patch, Mock
import sys
import os

sys.path.append(".")

from pydantic import FilePath
from paho.mqtt.client import ssl
from external_server.config import Config, ModuleConfig
from external_server.server import ExternalServer
from external_server.adapters.mqtt_adapter import MQTTClientAdapter
from tests.utils import EXAMPLE_MODULE_SO_LIB_PATH, ES_CONFIG_WITHOUT_MODULES


def _create_test_files():
    with open("ca.pem", "w") as f:
        f.write("ca")
    with open("certfile.pem", "w") as f:
        f.write("cert")
    with open("keyfile.pem", "w") as f:
        f.write("key")


class Test_Setting_Up_TLS_In_MQTT_Client(unittest.TestCase):

    def setUp(self) -> None:
        self.adapter = MQTTClientAdapter("company", "car", 2, "localhost", 1883)
        _create_test_files()

    def test_by_default_tls_is_not_set(self):
        self.assertIsNone(self.adapter._mqtt_client._ssl_context)

    def test_by_default_tls_ssl_context_is_none(self):
        self.assertIsNone(self.adapter._mqtt_client._ssl_context)

    @patch("ssl.SSLContext.load_verify_locations")
    @patch("ssl.SSLContext.load_cert_chain")
    def test_using_existing_files_for_tls_setup_sets_up_ssl_context(
        self, mock_load_cert_chain: Mock, mock_load_verify_locations: Mock
    ):
        mock_load_cert_chain.side_effect = lambda certfile, keyfile, keyfile_password: None
        mock_load_verify_locations.side_effect = lambda ca_certs: None
        self.adapter.tls_set("ca.pem", "certfile.pem", "keyfile.pem")
        self.assertIsNotNone(self.adapter._mqtt_client._ssl_context)
        # the server hostname verification in the certificate is required, thus
        self.assertFalse(self.adapter._mqtt_client._tls_insecure)

    def test_using_nonexistent_file_for_tls_setup_raises_exception(self):
        with self.assertRaises(FileNotFoundError):
            self.adapter.tls_set("nonexistent.pem", "certfile.pem", "keyfile.pem")
        with self.assertRaises(FileNotFoundError):
            self.adapter.tls_set("ca.pem", "nonexistent.pem", "keyfile.pem")
        with self.assertRaises(FileNotFoundError):
            self.adapter.tls_set("ca.pem", "certfile.pem", "nonexistent.pem")

    def tearDown(self) -> None:  # pragma: no cover
        if os.path.isfile("ca.pem"):
            os.remove("ca.pem")
        if os.path.isfile("certfile.pem"):
            os.remove("certfile.pem")
        if os.path.isfile("keyfile.pem"):
            os.remove("keyfile.pem")


class Test_TLS(unittest.TestCase):

    def setUp(self) -> None:
        example_module_config = ModuleConfig(
            lib_path=FilePath(EXAMPLE_MODULE_SO_LIB_PATH), config={}
        )
        self.config = Config(modules={"1000": example_module_config}, **ES_CONFIG_WITHOUT_MODULES)  # type: ignore
        self.es = ExternalServer(config=self.config)
        _create_test_files()

    @patch("ssl.SSLContext.load_verify_locations")
    @patch("ssl.SSLContext.load_cert_chain")
    def test_using_existing_files_for_tls_setup_sets_up_ssl_context(
        self, mock_load_cert_chain: Mock, mock_load_verify_locations: Mock
    ):
        mock_load_cert_chain.side_effect = lambda certfile, keyfile, keyfile_password: None
        mock_load_verify_locations.side_effect = lambda ca_certs: None
        self.es.tls_set("ca.pem", "certfile.pem", "keyfile.pem")
        self.assertIsNotNone(self.es._mqtt._mqtt_client._ssl_context)
        # the server hostname verification in the certificate is required, thus
        self.assertFalse(self.es._mqtt._mqtt_client._tls_insecure)

    def tearDown(self) -> None:  # pragma: no cover
        if os.path.isfile("ca.pem"):
            os.remove("ca.pem")
        if os.path.isfile("certfile.pem"):
            os.remove("certfile.pem")
        if os.path.isfile("keyfile.pem"):
            os.remove("keyfile.pem")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
