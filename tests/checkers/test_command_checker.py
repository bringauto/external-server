import unittest
import time
import sys
import logging

sys.path.append("lib/fleet-protocol/protobuf/compiled/python")

from ExternalProtocol_pb2 import Command  # type: ignore
from external_server.checkers.command_checker import CommandChecker


CHECKER_TIMEOUT = 0.15
logging.getLogger("CommandMessagesChecker").setLevel(logging.CRITICAL)


class Test_No_Commands_Stored_By_Checker(unittest.TestCase):

    def test_pop_commands_yields_empty_list_of_commands(self):
        checker = CommandChecker(CHECKER_TIMEOUT)
        cmd = checker.acknowledge_and_pop_commands(msg_counter=0)
        self.assertEqual(len(cmd), 0)


class Test_Pop_Command(unittest.TestCase):

    def setUp(self):
        self.checker = CommandChecker(CHECKER_TIMEOUT)
        self.cmd_1 = Command()
        self.cmd_2 = Command()
        self.cmd_3 = Command()
        self.checker.add_command(self.cmd_2, returned_from_api=False)
        self.checker.add_command(self.cmd_1, returned_from_api=False)
        self.checker.add_command(self.cmd_3, returned_from_api=False)

    def test_with_matching_msg_counter_yields_single_command_each_time(self):
        self.assertEqual(self.checker.acknowledge_and_pop_commands(msg_counter=0)[0][0], self.cmd_2)
        self.assertEqual(self.checker.acknowledge_and_pop_commands(msg_counter=1)[0][0], self.cmd_1)
        self.assertEqual(self.checker.acknowledge_and_pop_commands(msg_counter=2)[0][0], self.cmd_3)

    def test_without_matching_msg_counter_yields_single_command_each_time(self):
        self.assertEqual(self.checker.acknowledge_and_pop_commands(msg_counter=1), [])
        self.assertEqual(self.checker.acknowledge_and_pop_commands(msg_counter=2), [])

    def test_with_matching_msg_counter_yields_all_previously_commands_to_be_popped_without_maching_msg_counter(
        self,
    ):
        self.checker.acknowledge_and_pop_commands(msg_counter=1)
        self.checker.acknowledge_and_pop_commands(msg_counter=2)
        # the correct message counter value is 0, after popping cmd with this counter value
        # all three popped commands are returned in the correct order
        self.assertEqual(
            self.checker.acknowledge_and_pop_commands(msg_counter=0),
            [(self.cmd_2, False), (self.cmd_1, False), (self.cmd_3, False)],
        )

    def test_with_matching_msg_counter_is_not_affected_if_some_command_popped_in_wrong_order_were_already_returned(
        self,
    ):
        self.checker.acknowledge_and_pop_commands(msg_counter=1)
        self.assertEqual(
            self.checker.acknowledge_and_pop_commands(msg_counter=0),
            [(self.cmd_2, False), (self.cmd_1, False)],
        )
        # previously, all commands that were popped in wrong order were returned and the next command
        # popped with matching msg_counter is returned as usual
        self.assertEqual(
            self.checker.acknowledge_and_pop_commands(msg_counter=2), [(self.cmd_3, False)]
        )

    def test_with_counter_not_in_receivedf_acks_yields_empty_list(self):
        self.assertEqual(self.checker.acknowledge_and_pop_commands(msg_counter=3), [])


class Test_Exceeding_Timeout_For_Commands(unittest.TestCase):

    def setUp(self):
        self.checker = CommandChecker(CHECKER_TIMEOUT)
        command = Command()
        self.checker.add_command(command, False)

    def test_exceeding_timeout_sets_checkers_timeout_is_set_flag_to_true(self):
        self.assertFalse(self.checker.timeout.is_set())
        time.sleep(CHECKER_TIMEOUT + 0.01)
        self.assertTrue(self.checker.timeout.is_set())

    def test_timeout_event_is_unset_after_restarting_checker(self):
        time.sleep(CHECKER_TIMEOUT + 0.01)
        self.assertTrue(self.checker.timeout.is_set())
        self.checker.reset()
        self.assertFalse(self.checker.timeout.is_set())

    def test_timeout_is_not_set_when_command_is_acknowledged(self):
        self.assertFalse(self.checker.timeout.is_set())
        time.sleep(CHECKER_TIMEOUT / 2)
        self.checker.acknowledge_and_pop_commands(msg_counter=0)
        time.sleep(CHECKER_TIMEOUT / 2)
        self.assertFalse(self.checker.timeout.is_set())

    def test_timeout_is_not_set_when_all_commands_are_acknowledged(self):
        self.checker.add_command(Command(), False)
        self.assertFalse(self.checker.timeout.is_set())
        time.sleep(CHECKER_TIMEOUT / 2)
        self.checker.acknowledge_and_pop_commands(msg_counter=0)
        self.checker.acknowledge_and_pop_commands(msg_counter=1)
        time.sleep(CHECKER_TIMEOUT / 2 + 0.1)
        self.assertFalse(self.checker.timeout.is_set())

    def test_timeout_is_set_when_any_command_is_not_acknowledged(self):
        self.checker.add_command(Command(), False)
        self.assertFalse(self.checker.timeout.is_set())
        time.sleep(CHECKER_TIMEOUT / 2)
        self.checker.acknowledge_and_pop_commands(msg_counter=0)
        time.sleep(CHECKER_TIMEOUT / 2 + 0.1)
        self.assertTrue(self.checker.timeout.is_set())


if __name__ == "__main__":  # pragma: no cover
    unittest.main(buffer=True)
