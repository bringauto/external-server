import unittest
import time
import sys
import logging

sys.path.append("lib/fleet-protocol/protobuf/compiled/python")

from ExternalProtocol_pb2 import Status
from external_server.checker.order_checker import OrderChecker


ORDER_CHECKER_TIMEOUT = 0.15


class Test_Exceeding_Timeout_For_Commands(unittest.TestCase):

    def setUp(self):
        self.checker = OrderChecker(ORDER_CHECKER_TIMEOUT)

    def test_checker_accepts_status_with_counter_matching_checkers_counter(self):
        init_counter = self.checker.counter
        status = Status()
        status.messageCounter = self.checker.counter
        self.checker.check(status)
        self.assertEqual(self.checker.skipped_status_counter_vals, [])
        self.assertEqual(self.checker._received_statuses.queue, [(self.checker.counter, status)])
        self.assertEqual(self.checker.checked_statuses.get(), status)
        self.assertEqual(self.checker.counter, init_counter + 1)
        self.assertFalse(self.checker.timeout.is_set())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
