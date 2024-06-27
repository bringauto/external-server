import unittest
import sys
sys.path.append("lib/fleet-protocol/protobuf/compiled/python")

import ExternalProtocol_pb2 as external_protocol

from external_server.checker.command_messages_checker import CommandMessagesChecker


CHECKER_TIMEOUT = 0.55


class Test_No_Commands_Stored_By_Checker(unittest.TestCase):

    def test_pop_commands_yields_empty_list_of_commands(self):
        checker = CommandMessagesChecker(CHECKER_TIMEOUT)
        cmd = checker.pop_commands(msg_counter=0)
        self.assertEqual(len(cmd), 0)


class Test_Popped_Commands_From_Checker_With_Stored_Commands(unittest.TestCase):

    def test_are_in_the_order_they_were_received(self):
        checker = CommandMessagesChecker(CHECKER_TIMEOUT)

        cmd_1 = external_protocol.Command()
        cmd_2 = external_protocol.Command()
        cmd_3 = external_protocol.Command()

        checker.add_command(cmd_2, returned_from_api=False)
        checker.add_command(cmd_1, returned_from_api=False)
        checker.add_command(cmd_3, returned_from_api=False)

        popped_cmds = checker.pop_commands(msg_counter=0)
        self.assertEqual(len(popped_cmds), 3)
        self.assertEqual(popped_cmds[0][0], cmd_2)
        self.assertEqual(popped_cmds[0][1], False)


if __name__=="__main__":  # pragma: no cover
    unittest.main()