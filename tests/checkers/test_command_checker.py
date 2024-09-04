import unittest
import time
import sys
import logging

sys.path.append(".")
sys.path.append("lib/fleet-protocol/protobuf/compiled/python")

from InternalProtocol_pb2 import Device  # type: ignore
from external_server.models.structures import HandledCommand
from external_server.checkers.command_checker import PublishedCommandChecker
from external_server.models.messages import cmd_response


CHECKER_TIMEOUT = 0.09
# logging.getLogger("CommandMessagesChecker").setLevel(logging.CRITICAL)


class Test_No_Commands_Stored_By_Checker(unittest.TestCase):

    def test_pop_commands_yields_empty_list_of_commands(self):
        checker = PublishedCommandChecker(CHECKER_TIMEOUT)
        cmd = checker.pop(cmd_response("id", 0).commandResponse)
        self.assertEqual(len(cmd), 0)

    def test_oldest_counter_yields_none(self):
        checker = PublishedCommandChecker(CHECKER_TIMEOUT)
        self.assertEqual(checker._commands.oldest_command_counter, None)


class Test_Pop_Command(unittest.TestCase):

    def setUp(self):
        self.checker = PublishedCommandChecker(CHECKER_TIMEOUT)
        device = Device(module=1000, deviceType=0, deviceName="Test", deviceRole="test_1")
        self.cmd_0 = HandledCommand(b"", device=device)
        self.cmd_1 = HandledCommand(b"", device=device)
        self.cmd_2 = HandledCommand(b"", device=device)
        self.cmd_3 = HandledCommand(b"", device=device)
        self.checker.add(self.cmd_0)
        self.checker.add(self.cmd_1)
        self.checker.add(self.cmd_2)
        self.checker.add(self.cmd_3)

    def test_with_matching_counter_yields_single_command_each_time(self):
        self.assertEqual(self.checker.pop(cmd_response("id", 0).commandResponse), [self.cmd_0])
        self.assertEqual(self.checker.pop(cmd_response("id", 1).commandResponse), [self.cmd_1])
        self.assertEqual(self.checker.pop(cmd_response("id", 2).commandResponse), [self.cmd_2])

    def test_without_matching_counter_yields_empty_command_list(self):
        self.assertEqual(self.checker.pop(cmd_response("id", 1).commandResponse), [])
        self.assertEqual(self.checker.pop(cmd_response("id", 2).commandResponse), [])

    def test_with_matching_counter_yields_all_previous_commands_without_maching_counter(self):
        self.assertEqual(self.checker.pop(cmd_response("id", 1).commandResponse), [])
        self.assertEqual(self.checker.pop(cmd_response("id", 3).commandResponse), [])
        self.assertEqual(self.checker.pop(cmd_response("id", 2).commandResponse), [])
        # the correct message counter value is 0, after popping cmd with this counter value
        # all three popped commands are returned in the correct order
        cmds = self.checker.pop(cmd_response("id", 0).commandResponse)
        self.assertEqual(cmds, [self.cmd_0, self.cmd_1, self.cmd_2, self.cmd_3])

    def test_with_matching_counter_isnt_affected_if_some_commands_popped_in_wrong_order_already_returned(
        self,
    ):
        self.checker.pop(cmd_response("id", 1).commandResponse)
        self.assertEqual(
            self.checker.pop(cmd_response("id", 0).commandResponse),
            [self.cmd_0, self.cmd_1],
        )
        # previously, all commands that were popped in wrong order were returned and the next command
        # popped with matching msg_counter is returned as usual
        self.assertEqual(self.checker.pop(cmd_response("id", 2).commandResponse), [self.cmd_2])

    def test_with_counter_not_in_receivedf_acks_yields_empty_list(self):
        self.assertEqual(self.checker.pop(cmd_response("id", 3).commandResponse), [])



class Test_Popping_Commands(unittest.TestCase):

    def setUp(self):
        self.checker = PublishedCommandChecker(CHECKER_TIMEOUT)
        self.checker.set_counter(5)
        self.device = Device(module=1000, deviceType=0, deviceName="Test", deviceRole="test_1")

    def test_without_any_commands_in_checker_yields_empty_list(self):
        self.assertEqual(self.checker.pop(cmd_response("id", 0).commandResponse), [])
        self.assertEqual(self.checker.pop(cmd_response("id", 5).commandResponse), [])
        self.assertEqual(self.checker.pop(cmd_response("id", 10).commandResponse), [])
        self.assertEqual(self.checker.n_of_commands, 0)
        self.assertEqual(self.checker.command_counters, [])

    def test_with_matching_counter_with_only_single_command_waiting_for_response_yields_single_command(self):
        command = HandledCommand(b"", device=self.device)
        self.checker.add(command)
        self.assertEqual(self.checker.n_of_commands, 1)
        self.assertEqual(self.checker.pop(cmd_response("id", 5).commandResponse), [command])
        self.assertEqual(self.checker.n_of_commands, 0)
        self.assertEqual(self.checker.command_counters, [])

    def test_with_counter_not_corresponding_to_any_command_yields_empty_list_and_does_not_store_the_counter(self):
        command = HandledCommand(b"", device=self.device)
        self.checker.add(command)
        self.checker.add(command.copy())
        self.assertEqual(self.checker.pop(cmd_response("id", 4).commandResponse), [])
        self.assertEqual(self.checker.n_of_commands, 2)
        self.assertNotIn(4, self.checker._received_response_counters)
        self.assertEqual(self.checker.command_counters, [5, 6])

        self.assertEqual(self.checker.pop(cmd_response("id", 7).commandResponse), [])
        self.assertEqual(self.checker.n_of_commands, 2)
        self.assertNotIn(7, self.checker._received_response_counters)
        self.assertEqual(self.checker.command_counters, [5, 6])

    def test_with_counter_not_corresponding_to_other_than_oldest_command_yields_empty_list_and_stores_the_counter(self):
        command_1 = HandledCommand(b"", device=self.device)
        command_2 = HandledCommand(b"", device=self.device)
        # add two commands with counter 5 and 6
        self.checker.add(command_1)
        self.checker.add(command_2)
        self.assertEqual(self.checker.pop(cmd_response("id", 6).commandResponse), [])
        self.assertEqual(self.checker.n_of_commands, 2)
        self.assertEqual(self.checker.command_counters, [5, 6])

    def test_with_counter_corresponding_to_oldest_command_yields_single_command_and_removes_the_counter(self):
        command_1 = HandledCommand(b"", device=self.device)
        command_2 = HandledCommand(b"", device=self.device)
        # add two commands with counter 5 and 6
        self.checker.add(command_1)
        self.checker.add(command_2)
        self.assertEqual(self.checker.pop(cmd_response("id", 5).commandResponse), [command_1])
        self.assertEqual(self.checker.n_of_commands, 1)
        self.assertEqual(self.checker.command_counters, [6])

    def test_with_counter_first_matching_newer_and_then_older_command_finally_yields_both(self):
        command_1 = HandledCommand(b"", device=self.device)
        command_2 = HandledCommand(b"", device=self.device)
        # add three commands with counter 5 and 6
        self.checker.add(command_1)
        self.checker.add(command_2)
        self.assertEqual(self.checker.pop(cmd_response("id", 6).commandResponse), [])
        self.assertEqual(self.checker.pop(cmd_response("id", 5).commandResponse), [command_1, command_2])
        self.assertEqual(self.checker.n_of_commands, 0)
        self.assertEqual(self.checker.command_counters, [])

    def test_with_counter_finally_matching_oldest_counter_yields_list_of_commands_sorted_by_counter(self):
        command_1 = HandledCommand(b"", device=self.device)
        # add three commands with counter 5, 6 and 7
        self.checker.add(command_1) # counter 5
        command_2 = self.checker.add(command_1.copy()) # counter 6
        command_3 = self.checker.add(command_1.copy()) # counter 7
        command_4 = self.checker.add(command_1.copy()) # counter 8
        self.assertEqual(self.checker.pop(cmd_response("id", 6).commandResponse), [])
        self.assertEqual(self.checker.pop(cmd_response("id", 8).commandResponse), [])
        self.assertEqual(self.checker.pop(cmd_response("id", 7).commandResponse), [])
        self.assertEqual(
            self.checker.pop(cmd_response("id", 5).commandResponse),
            [command_1, command_2, command_3, command_4]
        )
        self.assertEqual(self.checker.n_of_commands, 0)
        self.assertEqual(self.checker.command_counters, [])


class Test_Exceeding_Timeout_For_Commands(unittest.TestCase):

    def setUp(self):
        self.checker = PublishedCommandChecker(CHECKER_TIMEOUT)
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
        self.checker.pop(cmd_response("id", 0).commandResponse)
        time.sleep(CHECKER_TIMEOUT / 2)
        self.assertFalse(self.checker.timeout_occured())

    def test_timeout_is_not_set_when_all_commands_are_acknowledged(self):
        self.checker.add(HandledCommand(b"", device=self.device))
        self.assertFalse(self.checker.timeout_occured())
        time.sleep(CHECKER_TIMEOUT / 2)
        self.checker.pop(cmd_response("id", 0).commandResponse)
        self.checker.pop(cmd_response("id", 1).commandResponse)
        time.sleep(CHECKER_TIMEOUT / 2 + 0.1)
        self.assertFalse(self.checker.timeout_occured())

    def test_timeout_is_set_when_any_command_is_not_acknowledged(self):
        self.checker.add(HandledCommand(b"", device=self.device))
        self.assertFalse(self.checker.timeout_occured())
        time.sleep(CHECKER_TIMEOUT / 2)
        self.checker.pop(cmd_response("id", 0).commandResponse)
        time.sleep(CHECKER_TIMEOUT / 2 + 0.1)
        self.assertTrue(self.checker.timeout_occured())


if __name__ == "__main__":  # pragma: no cover
    unittest.main(buffer=True, verbosity=2)
