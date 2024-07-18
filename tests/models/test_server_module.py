import unittest
import sys

sys.path.append('.')

from external_server.models.server_module import ServerModule
from external_server.config import ModuleConfig
from tests.utils import EXAMPLE_MODULE_SO_LIB_PATH


class Test_Creating_Server_Module(unittest.TestCase):

    def setUp(self):
        self.module_config = ModuleConfig(lib_path=EXAMPLE_MODULE_SO_LIB_PATH, config={})

    def test_creating_server_module(self):
        module = ServerModule(1000, "company", "car", self.module_config)
        self.assertIsNotNone(module.api_client)
        self.assertEqual(module.car, "car")
        self.assertEqual(module.company, "company")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()