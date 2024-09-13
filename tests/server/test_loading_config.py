import unittest
import json
import os
import sys

sys.path.append(".")

from external_server.config import ServerConfig, InvalidConfiguration


class Test_Cars(unittest.TestCase):

    def setUp(self) -> None:
        with open("./config/config.json.example") as config_file:
            self.config_dict = json.load(config_file)
        for item in self.config_dict["modules"].values():
            item["lib_path"] = "./test_lib"
        if not os.path.isfile("./test_lib"):
            with open("./test_lib", "w") as f:
                f.write("")

    def test_config_with_no_cars_raises_error(self):
        self.config_dict["cars"].clear()
        with self.assertRaises(InvalidConfiguration):
            ServerConfig(**self.config_dict)

    def test_config_single_cars_is_accepted(self):
        self.config_dict["cars"] = {"car1": {}}
        self.assertTrue(isinstance(ServerConfig(**self.config_dict), ServerConfig))

    def test_config_multiple_cars_are_accepted(self):
        # cars always have different names - ensured by using JSON
        self.config_dict["cars"] = {"car1": {}, "car2": {}}
        self.assertTrue(isinstance(ServerConfig(**self.config_dict), ServerConfig))

    def tearDown(self) -> None:
        if os.path.isfile("./test_lib"):
            os.remove("./test_lib")


class Test_Modules(unittest.TestCase):

    def setUp(self) -> None:
        with open("./config/config.json.example") as config_file:
            self.config_dict = json.load(config_file)
        for item in self.config_dict["modules"].values():
            item["lib_path"] = "./test_lib"
        if not os.path.isfile("./test_lib"):
            with open("./test_lib", "w") as f:
                f.write("")

    def test_config_with_no_modules_raises_error(self):
        self.config_dict["modules"].clear()
        with self.assertRaises(InvalidConfiguration):
            ServerConfig(**self.config_dict)

    def test_single_module_is_accepted(self):
        self.config_dict["modules"] = {"1": {"lib_path": "./test_lib", "config": {}}}
        self.assertTrue(isinstance(ServerConfig(**self.config_dict), ServerConfig))

    def test_multiple_modules_are_accepted(self):
        self.config_dict["modules"] = {
            "1": {"lib_path": "./test_lib", "config": {}},
            "2": {"lib_path": "./test_lib", "config": {}},
        }
        self.assertTrue(isinstance(ServerConfig(**self.config_dict), ServerConfig))

    def test_modules_missing_for_a_single_of_multiple_cars_raises_error(self):
        self.config_dict["modules"].clear()
        self.config_dict["cars"] = {"car_1": {}, "car_2": {}}
        self.config_dict["cars"]["car_1"]["modules"] = {"1": {"lib_path": "./test_lib", "config": {}}}
        # the second car has no module assigned
        with self.assertRaises(InvalidConfiguration):
            ServerConfig(**self.config_dict)

    def test_modules_defined_for_each_of_multiple_cars_is_accepted(self):
        self.config_dict["modules"].clear()
        self.config_dict["cars"] = {"car_1": {}, "car_2": {}}
        self.config_dict["cars"]["car_1"]["modules"] = {"1": {"lib_path": "./test_lib", "config": {}}}
        self.config_dict["cars"]["car_2"]["modules"] = {"1": {"lib_path": "./test_lib", "config": {}}}
        # the second car has no module assigned
        self.assertTrue(isinstance(ServerConfig(**self.config_dict), ServerConfig))

    def test_car_modules_can_be_empty_if_global_moduels_are_defined(self):
        self.config_dict["modules"] = {"1": {"lib_path": "./test_lib", "config": {}}}
        self.config_dict["cars"] = {"car_1": {}, "car_2": {}}
        # the first car has no module assigned, but global modules are defined
        self.config_dict["cars"]["car_1"]["modules"] = {}
        self.config_dict["cars"]["car_2"] = {"modules": {"2": {"lib_path": "./test_lib", "config": {}}}}
        self.assertTrue(isinstance(ServerConfig(**self.config_dict), ServerConfig))

    def tearDown(self) -> None:
        if os.path.isfile("./test_lib"):
            os.remove("./test_lib")

if __name__=="__main__":  # pragma: no cover
    unittest.main()