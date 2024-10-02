import unittest
import sys
from unittest.mock import patch, Mock

sys.path.append(".")

from external_server.server_module.command_waiting_thread import CommandWaitingThread
from external_server.adapters.api.adapter import APIClientAdapter
from external_server.config import ModuleConfig
from tests.utils import EXAMPLE_MODULE_SO_LIB_PATH
from external_server.models.events import EventQueue
from external_server.models.structures import GeneralErrorCode


class Test_No_Connection_With_Module_Gateway(unittest.TestCase):

    @patch('external_server.adapters.api.module_lib.ModuleLibrary.wait_for_command')
    def test_commands_are_not_stored_in_the_command_waiting_thread_queue_if_the_module_is_not_connected(self, mock_wait_result: Mock):
        module_config = ModuleConfig(lib_path=EXAMPLE_MODULE_SO_LIB_PATH, config={})
        connection_check_func = lambda: False
        command_thread = CommandWaitingThread(
            api_client=APIClientAdapter(module_config, "company_x", "car_a"),
            module_connection_check=connection_check_func,
            event_queue=EventQueue()
        )
        command_thread._api_adapter.init()
        self.assertEqual(command_thread.n_of_commands, 0)
        # mock command availability on API
        mock_wait_result.return_value = GeneralErrorCode.OK
        # pop_commands
        command_thread.poll_commands()

        self.assertEqual(command_thread.n_of_commands, 0)

    @patch('external_server.adapters.api.module_lib.ModuleLibrary.wait_for_command')
    def test_commands_are_retrieved_after_the_module_becomes_connected(self, mock_wait_result: Mock):
        module_config = ModuleConfig(lib_path=EXAMPLE_MODULE_SO_LIB_PATH, config={})
        self.connected = False
        def connection_check_func():
            return self.connected
        command_thread = CommandWaitingThread(
            api_client=APIClientAdapter(module_config, "company_x", "car_a"),
            module_connection_check=connection_check_func,
            event_queue=EventQueue()
        )
        command_thread._api_adapter.init()
        self.assertEqual(command_thread.n_of_commands, 0)
        # mock command availability on API
        mock_wait_result.return_value = GeneralErrorCode.OK
        # pop_commands
        command_thread.poll_commands()
        self.assertEqual(command_thread.n_of_commands, 0)
        # mock connection established
        self.connected = True
        command_thread.poll_commands()
        self.assertEqual(command_thread.n_of_commands, 1)


if __name__ == '__main__':
    unittest.main()