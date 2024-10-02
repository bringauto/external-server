import unittest
import sys

sys.path.append(".")

from external_server.server_module.server_module import ServerModule
from external_server.config import ModuleConfig
from tests.utils import EXAMPLE_MODULE_SO_LIB_PATH
from external_server.models.events import EventQueue


class Test_No_Connection_With_Module_Gateway(unittest.TestCase):

    def test_creating_server_module(self):
        module_config = ModuleConfig(lib_path=EXAMPLE_MODULE_SO_LIB_PATH, config={})
        module = ServerModule(
            1000, "company", "car", module_config, lambda: True, event_queue=EventQueue()
        )  # pragma: no cover
        self.assertIsNotNone(module.api)
        self.assertEqual(module.car, "car")
        self.assertEqual(module.company, "company")
        self.assertEqual(module.id, 1000)

if __name__ == '__main__':
    unittest.main()