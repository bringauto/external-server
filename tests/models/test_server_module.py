import unittest
import sys
import os

sys.path.append(".")

from external_server.server_module.server_module import ServerModule
from external_server.config import ModuleConfig
from external_server.models.events import EventQueue
from tests.utils import EXAMPLE_MODULE_SO_LIB_PATH


class Test_Creating_Server_Module(unittest.TestCase):

    def test_creating_server_module(self):
        module_config = ModuleConfig(lib_path=EXAMPLE_MODULE_SO_LIB_PATH, config={})
        module = ServerModule(
            1000, "company", "car", module_config, lambda: True, event_queue=EventQueue()
        )  # pragma: no cover
        self.assertIsNotNone(module.api)
        self.assertEqual(module.car, "car")
        self.assertEqual(module.company, "company")
        self.assertEqual(module.id, 1000)

    def test_creating_server_module_with_nonexistent_so_lib_raises_error(self):
        with open("test_file.so", "w") as f:
            f.write("test")
        config = ModuleConfig(lib_path="test_file.so", config={})
        os.remove("test_file.so")
        with self.assertRaises(RuntimeError):
            ServerModule(1000, "company", "car", config, lambda: True, event_queue=EventQueue())  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
