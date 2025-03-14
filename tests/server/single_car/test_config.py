import unittest
import sys

sys.path.append(".")

import pydantic
from pydantic import FilePath

from external_server.config import CarConfig, ModuleConfig
from tests.utils import EXAMPLE_MODULE_SO_LIB_PATH


class Test_Config_Validation(unittest.TestCase):

    def setUp(self) -> None:
        self.module_config = ModuleConfig(lib_path=FilePath(EXAMPLE_MODULE_SO_LIB_PATH), config={})
        self.valid_config_dict = {
            "company_name": "bring_auto",
            "car_name": "car_1",
            "mqtt_address": "127.0.0.1",
            "mqtt_port": 1884,
            "mqtt_timeout": 4,
            "timeout": 5,
            "send_invalid_command": False,
            "sleep_duration_after_connection_refused": 7,
            "modules": {"123": self.module_config},
        }

    def test_config_with_all_fields_valid_and_provided_causes_no_error(self):
        CarConfig(**self.valid_config_dict)

    def test_config_with_any_field_missing_causes_error(self):
        for key in self.valid_config_dict:
            with self.subTest(key=key):
                config_dict = self.valid_config_dict.copy()
                config_dict.pop(key)
                with self.assertRaises(ValueError):
                    CarConfig(**config_dict)

    def test_only_lowercase_letters_underscore_and_numerals_are_valid_company_and_car_names(self):
        for name in ["valid_name", "valid_name_2", "valid_2", "valid_2_name"]:
            with self.subTest(name=name):
                config_dict = self.valid_config_dict.copy()
                config_dict["company_name"] = name
                config_dict["car_name"] = name
                CarConfig(**config_dict)
        for name in ["InvalidName", "invalid-name", "invalid name", "invalid_name!"]:
            with self.subTest(name=name):
                config_dict = self.valid_config_dict.copy()
                config_dict["company_name"] = name
                with self.assertRaises(ValueError):
                    CarConfig(**config_dict)

    def test_empty_mqtt_address_raises_validation_error(self):
        with self.assertRaises(pydantic.ValidationError):
            config_dict = self.valid_config_dict.copy()
            config_dict["mqtt_address"] = ""
            CarConfig(**config_dict)

    def test_mqtt_port_must_be_nonegative_integer(self):
        for port in [0, 1, 1000, "1883"]:
            with self.subTest(port=port):
                config_dict = self.valid_config_dict.copy()
                config_dict["mqtt_port"] = port
                CarConfig(**config_dict)

        for port in [-1, -1000, 0.1, ""]:
            with self.subTest(port=port), self.assertRaises(pydantic.ValidationError):
                config_dict = self.valid_config_dict.copy()
                config_dict["mqtt_port"] = port
                CarConfig(**config_dict)

    def test_timeouts_is_must_be_nonegative(self):
        for timeout in [0, 1, 0.1, 1000, "1883"]:
            with self.subTest(timeout=timeout):
                config_dict = self.valid_config_dict.copy()
                config_dict["mqtt_timeout"] = timeout
                config_dict["timeout"] = timeout
                CarConfig(**config_dict)

        for timeout in [-1, -1000, ""]:
            with self.subTest(timeout=timeout), self.assertRaises(pydantic.ValidationError):
                config_dict = self.valid_config_dict.copy()
                config_dict["mqtt_timeout"] = timeout
                config_dict["timeout"] = timeout
                CarConfig(**config_dict)

    def test_sleep_duration_after_connection_refused_must_be_nonegative_float(self):
        for duration in [0, 1, 1000, 0.1]:
            with self.subTest(duration=duration):
                config_dict = self.valid_config_dict.copy()
                config_dict["sleep_duration_after_connection_refused"] = duration
                CarConfig(**config_dict)

        for duration in [-1, -1000, ""]:
            with self.subTest(duration=duration), self.assertRaises(pydantic.ValidationError):
                config_dict = self.valid_config_dict.copy()
                config_dict["sleep_duration_after_connection_refused"] = duration
                CarConfig(**config_dict)

    def test_no_modules_raise_validation_error(self):
        with self.assertRaises(pydantic.ValidationError):
            config_dict = self.valid_config_dict.copy()
            config_dict["modules"] = {}
            CarConfig(**config_dict)


if __name__ == "__main__":  # pragma: no cover
    unittest.main(buffer=True)
