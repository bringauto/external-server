import unittest
import time
import sys
import logging

sys.path.append("lib/fleet-protocol/protobuf/compiled/python")

from InternalProtocol_pb2 import Device  # type: ignore
from external_server.models.structures import HandledCommand
from external_server.checkers.command_checker import CommandChecker


CHECKER_TIMEOUT = 0.09
logging.getLogger("CommandMessagesChecker").setLevel(logging.CRITICAL)


class Test_No_Commands_Stored_By_Checker(unittest.TestCase):

    def test_pop_commands_yields_empty_list_of_commands(self):
        checker = CommandChecker(CHECKER_TIMEOUT)
        cmd = checker.pop_commands(counter=0)
        self.assertEqual(len(cmd), 0)

    def test_oldest_counter_yields_none(self):
        checker = CommandChecker(CHECKER_TIMEOUT)
        self.assertEqual(checker._commands.oldest_counter, None)


class Test_Pop_Command(unittest.TestCase):

    def setUp(self):
        self.checker = CommandChecker(CHECKER_TIMEOUT)
        device = Device(module=1000, deviceType=0, deviceName="Test", deviceRole="test_1")
        self.cmd_1 = HandledCommand(b"", device=device)
        self.cmd_2 = HandledCommand(b"", device=device)
        self.cmd_3 = HandledCommand(b"", device=device)
        self.checker.add(self.cmd_2)
        self.checker.add(self.cmd_1)
        self.checker.add(self.cmd_3)

    def test_with_matching_counter_yields_single_command_each_time(self):
        self.assertEqual(self.checker.pop_commands(counter=0)[0], self.cmd_2)
        self.assertEqual(self.checker.pop_commands(counter=1)[0], self.cmd_1)
        self.assertEqual(self.checker.pop_commands(counter=2)[0], self.cmd_3)
        print(self.cmd_3.counter)

    def test_without_matching_counter_yields_empty_command_list(self):
        self.assertEqual(self.checker.pop_commands(counter=1), [])
        self.assertEqual(self.checker.pop_commands(counter=2), [])

    def test_with_matching_counter_yields_all_previous_commands_without_maching_counter(self):
        self.assertEqual(self.checker.pop_commands(counter=1), [])
        self.assertEqual(self.checker.pop_commands(counter=2), [])
        # the correct message counter value is 0, after popping cmd with this counter value
        # all three popped commands are returned in the correct order
        self.assertEqual(
            self.checker.pop_commands(counter=0),
            [self.cmd_2, self.cmd_1, self.cmd_3],
        )

    def test_with_matching_counter_isnt_affected_if_some_commands_popped_in_wrong_order_already_returned(
        self,
    ):
        self.checker.pop_commands(counter=1)
        self.assertEqual(
            self.checker.pop_commands(counter=0),
            [self.cmd_2, self.cmd_1],
        )
        # previously, all commands that were popped in wrong order were returned and the next command
        # popped with matching msg_counter is returned as usual
        self.assertEqual(self.checker.pop_commands(counter=2), [self.cmd_3])

    def test_with_counter_not_in_receivedf_acks_yields_empty_list(self):
        self.assertEqual(self.checker.pop_commands(counter=3), [])


class Test_Exceeding_Timeout_For_Commands(unittest.TestCase):

    def setUp(self):
        self.checker = CommandChecker(CHECKER_TIMEOUT)
        self.device = Device(module=1000, deviceType=0, deviceName="Test", deviceRole="test_1")
        command = HandledCommand(b"", device=self.device)
        self.checker.add(command)

    def test_exceeding_timeout_sets_checkers_timeout_is_set_flag_to_true(self):
        self.assertFalse(self.checker.timeout_occured())
        time.sleep(CHECKER_TIMEOUT + 0.01)
        self.assertTrue(self.checker.timeout_occured())

    def test_timeout_event_is_unset_after_restarting_checker(self):
        time.sleep(CHECKER_TIMEOUT + 0.01)
        self.assertTrue(self.checker.timeout_occured())
        self.checker.reset()
        self.assertFalse(self.checker.timeout_occured())

    def test_timeout_is_not_set_when_command_is_acknowledged(self):
        self.assertFalse(self.checker.timeout_occured())
        time.sleep(CHECKER_TIMEOUT / 2)
        self.checker.pop_commands(counter=0)
        time.sleep(CHECKER_TIMEOUT / 2)
        self.assertFalse(self.checker.timeout_occured())

    def test_timeout_is_not_set_when_all_commands_are_acknowledged(self):
        self.checker.add(HandledCommand(b"", device=self.device))
        self.assertFalse(self.checker.timeout_occured())
        time.sleep(CHECKER_TIMEOUT / 2)
        self.checker.pop_commands(counter=0)
        self.checker.pop_commands(counter=1)
        time.sleep(CHECKER_TIMEOUT / 2 + 0.1)
        self.assertFalse(self.checker.timeout_occured())

    def test_timeout_is_set_when_any_command_is_not_acknowledged(self):
        self.checker.add(HandledCommand(b"", device=self.device))
        self.assertFalse(self.checker.timeout_occured())
        time.sleep(CHECKER_TIMEOUT / 2)
        self.checker.pop_commands(counter=0)
        time.sleep(CHECKER_TIMEOUT / 2 + 0.1)
        self.assertTrue(self.checker.timeout_occured())


if __name__ == "__main__":  # pragma: no cover
    unittest.main(buffer=True, verbosity=2)
