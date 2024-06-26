import time
import pytest
import sys

sys.path.append("lib/fleet-protocol/protobuf/compiled/python")

import ExternalProtocol_pb2 as external_protocol


from external_server.checker.command_messages_checker import CommandMessagesChecker


class TestException(Exception):
    __test__ = False


class TestCommandMessagesChecker:
    TIMEOUT = 1
    SLEEP_TIME = TIMEOUT + 0.1

    # Pop a command when there are no commands
    def test_no_added_commands(self):
        checker = CommandMessagesChecker(TestException(), self.TIMEOUT)
        result = checker.pop_commands(0)
        assert len(result) == 0

    # Add a command to the checker and pop it in correct order
    def test_add_and_pop_command_correct_order(self):
        checker = CommandMessagesChecker(TestException(), self.TIMEOUT)
        command = external_protocol.Command()
        checker.add_command(command, False)
        result = checker.pop_commands(0)
        assert len(result) == 1
        assert result[0][0] == command
        assert result[0][1] == False

    # Add multiple commands to the checker and pop them in correct order
    def test_add_and_pop_multiple_commands_correct_order(self):
        checker = CommandMessagesChecker(TestException(), self.TIMEOUT)
        command1 = external_protocol.Command()
        command2 = external_protocol.Command()
        checker.add_command(command1, False)
        checker.add_command(command2, True)

        result = checker.pop_commands(0)
        assert len(result) == 1
        assert result[0][0] == command1
        assert result[0][1] == False

        result = checker.pop_commands(1)
        assert len(result) == 1
        assert result[0][0] == command2
        assert result[0][1] == True

    # Pop a command in wrong order
    def test_pop_command_wrong_order(self):
        checker = CommandMessagesChecker(TestException(), self.TIMEOUT)
        command1 = external_protocol.Command()
        command2 = external_protocol.Command()
        checker.add_command(command1, False)
        checker.add_command(command2, True)

        result = checker.pop_commands(1)
        assert len(result) == 0

        result = checker.pop_commands(0)
        assert len(result) == 2
        assert result[0][0] == command1
        assert result[0][1] == False
        assert result[1][0] == command2
        assert result[1][1] == True

    # Wait for timeout
    def test_wait_for_timeout(self):
        checker = CommandMessagesChecker(TestException(), self.TIMEOUT)
        command = external_protocol.Command()
        checker.add_command(command, False)

        time.sleep(self.SLEEP_TIME)
        with pytest.raises(TestException):
            checker.check_time_out()

    # Wait for timeout after checker reset
    def test_wait_for_timeout_after_reset(self):
        checker = CommandMessagesChecker(TestException(), self.TIMEOUT)
        command = external_protocol.Command()
        checker.add_command(command, False)
        checker.reset()

        time.sleep(self.SLEEP_TIME)

        checker.check_time_out()
