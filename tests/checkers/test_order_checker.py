import unittest
import time
import sys
import logging

sys.path.append("lib/fleet-protocol/protobuf/compiled/python")

from ExternalProtocol_pb2 import Status
from external_server.checker.order_checker import OrderChecker


logging.getLogger("OrderChecker").setLevel(logging.CRITICAL)
ORDER_CHECKER_TIMEOUT = 0.15


class Test_Exceeding_Timeout_For_Commands(unittest.TestCase):

    def setUp(self):
        self.checker = OrderChecker(ORDER_CHECKER_TIMEOUT)

    def test_checker_accepts_status_with_counter_matching_checkers_counter(self):
        init_counter = self.checker.counter
        self.checker.check(Status(messageCounter=init_counter))
        self.assertEqual(self.checker.missing_status_counter_vals, [])
        self.assertEqual(self.checker.checked_statuses.get().messageCounter, init_counter)
        self.assertEqual(self.checker.counter, init_counter + 1)
        self.assertFalse(self.checker.timeout.is_set())

    def test_checker_does_not_accept_status_with_counter_greater_than_checkers_counter(self):
        init_counter = self.checker.counter
        self.checker.check(Status(messageCounter=self.checker.counter + 1))
        # checker stores missing counter values
        self.assertEqual(self.checker.missing_status_counter_vals, [1, 2])
        self.assertEqual(self.checker.counter, init_counter)
        self.assertFalse(self.checker.timeout.is_set())

    def test_checker_does_not_accept_status_with_counter_less_than_checkers_counter(self):
        init_counter = self.checker.counter
        self.checker.check(Status(messageCounter=self.checker.counter - 1))
        # checker stores missing counter values
        self.assertEqual(self.checker.missing_status_counter_vals, [])
        self.assertEqual(self.checker.counter, init_counter)
        self.assertFalse(self.checker.timeout.is_set())


class Test_Checking_Multiple_Statuses(unittest.TestCase):

    def setUp(self):
        self.checker = OrderChecker(ORDER_CHECKER_TIMEOUT)

    def test_in_any_order_eventually_not_skipping_any_counter_value_yields_statuses_in_correct_order(self):
        self.checker.check(Status(messageCounter=3))
        self.checker.check(Status(messageCounter=1))
        self.checker.check(Status(messageCounter=2))
        self.checker.check(Status(messageCounter=5))
        self.checker.check(Status(messageCounter=4))

        gotten_statuses = [self.checker.get_status() for _ in range(5)]
        self.assertEqual(gotten_statuses[0].messageCounter, 1)
        self.assertEqual(gotten_statuses[1].messageCounter, 2)
        self.assertEqual(gotten_statuses[2].messageCounter, 3)
        self.assertEqual(gotten_statuses[3].messageCounter, 4)
        self.assertEqual(gotten_statuses[4].messageCounter, 5)

    def test_skipping_counter_value_prevents_any_following_calls_to_get_status_from_returning_any_message(self):
        self.checker.check(Status(messageCounter=1))
        # message counter value 2 is skipped
        self.checker.check(Status(messageCounter=3))
        self.checker.check(Status(messageCounter=4))

        self.assertEqual(self.checker.get_status().messageCounter, 1)
        # messages coming after the skipped counter value are not returned
        self.assertIsNone(self.checker.get_status())
        self.assertIsNone(self.checker.get_status())


class Test_Timeout(unittest.TestCase):

    def setUp(self):
        self.checker = OrderChecker(timeout=ORDER_CHECKER_TIMEOUT)

    def test_single_message_with_correct_counter_value_does_not_cause_timeout(self):
        self.checker.check(Status(messageCounter=1))
        time.sleep(ORDER_CHECKER_TIMEOUT + 0.01)
        self.assertFalse(self.checker.timeout.is_set())

    def test_single_message_with_greater_counter_value_than_checkers_counter_does_cause_timeout(self):
        self.checker.check(Status(messageCounter=2))
        time.sleep(ORDER_CHECKER_TIMEOUT + 0.01)
        self.assertTrue(self.checker.timeout.is_set())

    def test_multiple_messages_with_any_counter_values_skipped_lead_to_timeout_if_missing_val_not_delivered(self):
        self.checker.check(Status(messageCounter=1))
        self.checker.check(Status(messageCounter=2))
        self.checker.check(Status(messageCounter=4))
        time.sleep(ORDER_CHECKER_TIMEOUT + 0.01)
        self.assertTrue(self.checker.timeout.is_set())

    def test_multiple_messages_with_only_incorrect_order_of_vals_but_no_value_skipped_do_not_lead_to_timeout(self):
        self.checker.check(Status(messageCounter=2))
        self.checker.check(Status(messageCounter=1))
        self.checker.check(Status(messageCounter=4))
        self.checker.check(Status(messageCounter=3))
        time.sleep(ORDER_CHECKER_TIMEOUT + 0.01)
        self.assertFalse(self.checker.timeout.is_set())


class Test_Resetting_Checker(unittest.TestCase):

    def setUp(self):
        self.checker = OrderChecker(ORDER_CHECKER_TIMEOUT)
        self.checker.check(Status(messageCounter=1))
        self.checker.check(Status(messageCounter=2))
        self.checker.check(Status(messageCounter=3))

    def test_resetting_checker_clears_all_stored_messages(self):
        self.checker.reset()
        self.assertIsNone(self.checker.get_status())
        self.assertIsNone(self.checker.get_status())
        self.assertIsNone(self.checker.get_status())

    def test_resetting_checker_resets_checkers_counter(self):
        self.assertEqual(self.checker.counter, 4)
        self.checker.reset()
        self.assertEqual(self.checker.counter, 1)

    def test_resetting_checker_clears_timeout(self):
        self.checker.check(Status(messageCounter=5000))
        time.sleep(ORDER_CHECKER_TIMEOUT + 0.01)
        self.assertTrue(self.checker.timeout.is_set())
        self.checker.reset()
        self.assertFalse(self.checker.timeout.is_set())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
