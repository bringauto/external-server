import unittest
import time
import sys
import logging

sys.path.append(".")

from fleet_protocol_protobuf_files.ExternalProtocol_pb2 import Status
from external_server.checkers.status_checker import StatusChecker
from external_server.models.events import EventQueue


logging.getLogger(StatusChecker.__name__).setLevel(logging.CRITICAL)
ORDER_CHECKER_TIMEOUT = 0.05


class Test_Initializing_Status_Checker_Counter(unittest.TestCase):

    def test_status_checker_can_be_set_if_no_statuses_were_yet_received(self):
        checker = StatusChecker(ORDER_CHECKER_TIMEOUT, EventQueue())
        checker.set_counter(5)
        self.assertEqual(checker.counter, 5)

    def test_status_checker_is_not_set_if_statuses_were_yet_received(self):
        checker = StatusChecker(ORDER_CHECKER_TIMEOUT, EventQueue())
        checker.set_counter(0)
        checker.check(Status(messageCounter=0))

        # the counter was updated to 1 after receiving the status
        self.assertEqual(checker.counter, 1)
        checker.set_counter(5)
        # the counter cannot be initialized again after already receiving a status
        self.assertEqual(checker.counter, 1)


class Test_Receiving_Status(unittest.TestCase):

    def setUp(self):
        self.checker = StatusChecker(ORDER_CHECKER_TIMEOUT, EventQueue())
        self.checker.set_counter(4)

    def test_checker_accepts_status_with_counter_matching_checkers_counter(self):
        expected = self.checker.counter
        self.checker.check(Status(messageCounter=expected))

        self.assertEqual(self.checker.counter, expected + 1, "Counter was updated")
        self.assertEqual(self.checker.skipped_counters, [], "No missing counter values")
        self.assertEqual(
            self.checker.checked.get().messageCounter, expected, "Status is accessible"
        )

    def test_checker_does_not_accept_status_with_counter_greater_than_checkers_counter(self):
        expected = self.checker.counter
        self.checker.check(Status(messageCounter=expected + 3))
        # checker stores missing counter values
        missed_vals = [expected, expected + 1, expected + 2]

        self.assertEqual(self.checker.skipped_counters, missed_vals)
        self.assertEqual(
            self.checker.checked.qsize(),
            0,
            "Status was not added to checked (accessible) statuses)",
        )
        self.assertEqual(self.checker.counter, expected)

    def test_checker_does_not_accept_status_with_counter_less_than_checkers_counter(self):
        expected = self.checker.counter
        self.checker.check(Status(messageCounter=self.checker.counter - 1))
        self.assertEqual(self.checker.skipped_counters, [], "No missing values stored")
        self.assertEqual(self.checker.checked.qsize(), 0, "Status was not added to checked")
        self.assertEqual(self.checker.counter, expected, "Counter was not updated")

    def test_checking_status_multiple_times_adds_it_to_checkers_queue_only_once(self):
        expected = self.checker.counter

        status = Status(messageCounter=self.checker.counter)
        self.checker.check(status)
        self.checker.check(status)
        self.assertEqual(self.checker.counter, expected + 1)
        self.assertFalse(self.checker.timeout_occurred())
        self.assertEqual(self.checker.get(), status)
        self.assertIsNone(self.checker.get())


class Test_Checking_Multiple_Statuses(unittest.TestCase):

    def setUp(self):
        self.checker = StatusChecker(ORDER_CHECKER_TIMEOUT, EventQueue())
        self.checker.set_counter(1)

    def test_in_any_order_eventually_not_skipping_any_counter_value_yields_statuses_in_correct_order(
        self,
    ):
        self.checker.check(Status(messageCounter=3))
        self.checker.check(Status(messageCounter=1))
        self.checker.check(Status(messageCounter=2))
        self.checker.check(Status(messageCounter=5))
        self.checker.check(Status(messageCounter=4))

        gotten_statuses = [self.checker.get() for _ in range(5)]
        self.assertEqual(gotten_statuses[0].messageCounter, 1)
        self.assertEqual(gotten_statuses[1].messageCounter, 2)
        self.assertEqual(gotten_statuses[2].messageCounter, 3)
        self.assertEqual(gotten_statuses[3].messageCounter, 4)
        self.assertEqual(gotten_statuses[4].messageCounter, 5)

    def test_skipping_counter_value_prevents_any_following_calls_to_get_status_from_returning_any_message(
        self,
    ):
        self.checker.check(Status(messageCounter=1))
        # message counter value 2 is skipped
        self.checker.check(Status(messageCounter=3))
        self.checker.check(Status(messageCounter=4))

        self.assertEqual(self.checker.get().messageCounter, 1)
        # messages coming after the skipped counter value are not returned
        self.assertIsNone(self.checker.get())
        self.assertIsNone(self.checker.get())


class Test_Skipped_Values(unittest.TestCase):

    def setUp(self) -> None:
        self.checker = StatusChecker(ORDER_CHECKER_TIMEOUT, EventQueue())
        self.checker.set_counter(1)

    def test_skipped_values_are_stored_and_checked_for_timeout(self):
        self.checker._store_skipped_counter_values(3)
        self.assertEqual(self.checker.skipped_counters, [1, 2])

    def test_counter_matching_current_counter_value_yields_no_skipped_values(self):
        self.checker._store_skipped_counter_values(self.checker.counter)
        self.assertEqual(self.checker.skipped_counters, [])

    def test_for_each_skipped_value_timer_is_started(self):
        self.checker._store_skipped_counter_values(3)  # two skipped values
        self.assertTrue(self.checker._skipped.queue[0][1].is_alive())
        self.assertTrue(self.checker._skipped.queue[1][1].is_alive())

    def test_adding_value_less_or_equal_to_newest_skipped_value_has_no_effect(self):
        self.checker._store_skipped_counter_values(5)
        self.assertEqual(self.checker.skipped_counters, [1, 2, 3, 4])
        self.checker._store_skipped_counter_values(3)
        self.assertEqual(self.checker.skipped_counters, [1, 2, 3, 4])


class Test_Checking_Statuses(unittest.TestCase):

    def setUp(self):
        self.checker = StatusChecker(ORDER_CHECKER_TIMEOUT, EventQueue())
        self.checker.set_counter(1)

    def test_status_is_stored_as_received_when_counter_is_greater_than_expected(self):
        expected = self.checker.counter
        self.checker.check(Status(messageCounter=expected + 1))
        self.checker.check(Status(messageCounter=expected + 25))
        self.assertEqual(self.checker._received.qsize(), 2)
        self.assertEqual(self.checker._received.get()[0], expected + 1)
        self.assertEqual(self.checker._received.get()[0], expected + 25)

    def test_status_is_ignored_when_counter_is_less_than_expected(self):
        expected = self.checker.counter
        self.checker.check(Status(messageCounter=expected - 1))
        self.assertEqual(self.checker._received.qsize(), 0)

    def test_status_stored_as_checked_if_counter_matches_expected(self):
        expected = self.checker.counter
        self.checker.check(Status(messageCounter=expected))
        self.assertEqual(self.checker._received.qsize(), 0)
        self.assertEqual(self.checker._checked.qsize(), 1)
        self.assertEqual(self.checker._checked.get().messageCounter, expected)

    def test_status_is_stored_as_received_if_counter_is_greater_than_expected(self):
        expected = self.checker.counter
        self.checker.check(Status(messageCounter=expected + 1))
        self.assertEqual(self.checker._received.qsize(), 1)

    def test_all_skipped_values_are_stored_if_status_with_counter_greater_than_expected_was_received(
        self,
    ):
        self.checker.check(Status(messageCounter=4))
        self.assertEqual(self.checker.skipped_counters, [1, 2, 3])

    def test_all_skipped_values_are_stored_until_status_with_expected_counter_is_received(self):
        self.checker.check(Status(messageCounter=4))
        self.assertEqual(self.checker.skipped_counters, [1, 2, 3])
        self.checker.check(Status(messageCounter=2))
        self.assertEqual(self.checker.skipped_counters, [1, 2, 3])
        self.checker.check(Status(messageCounter=3))
        self.assertEqual(self.checker.skipped_counters, [1, 2, 3])
        self.checker.check(Status(messageCounter=1))
        self.assertEqual(self.checker.skipped_counters, [])

    def test_for_every_skipped_counter_a_timer_is_started(self):
        self.checker.check(Status(messageCounter=4))
        self.assertTrue(self.checker._skipped.queue[0][1].is_alive())
        self.assertTrue(self.checker._skipped.queue[1][1].is_alive())
        self.assertTrue(self.checker._skipped.queue[2][1].is_alive())

    def test_all_timers_are_stopped_when_clearing_the_skipped_counter_queue(self):
        self.checker.check(Status(messageCounter=3))
        timers = [timer for _, timer in self.checker._skipped.queue]
        self.checker.check(Status(messageCounter=2))
        self.checker.check(Status(messageCounter=1))
        self.assertEqual(len(timers), 2)
        for timer in timers:
            self.assertFalse(timer.is_alive())

    def test_received_statuses_are_moved_to_checked_after_getting_all_skipped_counters(self):
        self.checker.check(Status(messageCounter=3))
        self.assertEqual(self.checker._received.qsize(), 1)
        self.assertEqual(self.checker._checked.qsize(), 0)
        self.checker.check(Status(messageCounter=2))
        self.assertEqual(self.checker._received.qsize(), 2)
        self.assertEqual(self.checker._checked.qsize(), 0)
        self.checker.check(Status(messageCounter=1))
        self.assertEqual(self.checker._received.qsize(), 0)
        self.assertEqual(self.checker._checked.qsize(), 3)

    def test_single_received_status_with_counter_less_or_equal_to_expected_is_moved_to_checked(
        self,
    ):
        self.checker.check(Status(messageCounter=3))
        self.assertEqual(self.checker._received.qsize(), 1)
        self.assertEqual(self.checker._checked.qsize(), 0)
        self.checker.check(Status(messageCounter=1))
        self.assertEqual(self.checker._received.qsize(), 1)
        self.assertEqual(self.checker._checked.qsize(), 1)
        self.checker.check(Status(messageCounter=2))
        self.assertEqual(self.checker._received.qsize(), 0)
        self.assertEqual(self.checker._checked.qsize(), 3)

    def test_multiple_received_statuses_with_counter_less_or_equal_to_expected_are_moved_to_checked(
        self,
    ):
        self.checker.check(Status(messageCounter=4))

        self.assertEqual(self.checker._received.qsize(), 1)
        self.assertEqual(self.checker._checked.qsize(), 0)
        self.assertEqual(self.checker.skipped_counters, [1, 2, 3])

        self.checker.check(Status(messageCounter=2))
        self.assertEqual(self.checker._received.qsize(), 2)
        self.assertEqual(self.checker._checked.qsize(), 0)
        self.assertEqual(self.checker.skipped_counters, [1, 2, 3])

        self.checker.check(Status(messageCounter=1))
        self.assertEqual(self.checker._received.qsize(), 1)
        self.assertEqual(self.checker._checked.qsize(), 2)
        self.assertEqual(self.checker.skipped_counters, [3])

    def test_skipped_values_are_cleared_up_to_expected_value(self):
        self.checker.check(Status(messageCounter=5))
        self.assertEqual(self.checker.skipped_counters, [1, 2, 3, 4])
        self.checker.check(Status(messageCounter=2))
        self.checker.check(Status(messageCounter=1))
        self.assertEqual(self.checker.skipped_counters, [3, 4])


class Test_Timeout(unittest.TestCase):

    def setUp(self):
        self.checker = StatusChecker(ORDER_CHECKER_TIMEOUT, EventQueue())
        self.checker.set_counter(1)

    def test_single_message_with_correct_counter_value_does_not_cause_timeout(self):
        self.checker.check(Status(messageCounter=1))
        time.sleep(ORDER_CHECKER_TIMEOUT + 0.01)
        self.assertFalse(self.checker.timeout_occurred())

    def test_single_message_with_greater_counter_value_than_checkers_counter_does_cause_timeout(
        self,
    ):
        self.checker.check(Status(messageCounter=2))
        time.sleep(ORDER_CHECKER_TIMEOUT + 0.01)
        self.assertTrue(self.checker.timeout_occurred())

    def test_multiple_messages_with_any_counter_values_skipped_lead_to_timeout_if_missing_val_not_delivered(
        self,
    ):
        self.checker.check(Status(messageCounter=1))
        self.checker.check(Status(messageCounter=2))
        self.checker.check(Status(messageCounter=4))
        time.sleep(ORDER_CHECKER_TIMEOUT + 0.01)
        self.assertTrue(self.checker.timeout_occurred())

    def test_multiple_messages_with_incorrect_order_but_no_value_skipped_do_not_yield_timeout(self):
        self.checker.check(Status(messageCounter=2))
        self.checker.check(Status(messageCounter=1))
        self.checker.check(Status(messageCounter=4))
        self.checker.check(Status(messageCounter=3))
        time.sleep(ORDER_CHECKER_TIMEOUT + 0.01)
        self.assertFalse(self.checker.timeout_occurred())


class Test_Resetting_Checker(unittest.TestCase):

    def setUp(self):
        self.checker = StatusChecker(ORDER_CHECKER_TIMEOUT, EventQueue())
        self.checker.set_counter(1)
        self.checker.check(Status(messageCounter=1))
        self.checker.check(Status(messageCounter=2))
        self.checker.check(Status(messageCounter=3))

    def test_resetting_checker_clears_all_stored_messages(self):
        self.checker.reset()
        self.assertIsNone(self.checker.get())
        self.assertIsNone(self.checker.get())
        self.assertIsNone(self.checker.get())

    def test_resetting_checker_resets_checkers_counter(self):
        self.assertEqual(self.checker.counter, 4)
        self.checker.reset()
        self.assertEqual(self.checker.counter, 1)

    def test_resetting_checker_clears_timeout(self):
        self.checker.check(Status(messageCounter=6))
        time.sleep(ORDER_CHECKER_TIMEOUT + 0.01)
        self.assertTrue(self.checker.timeout_occurred())
        self.checker.reset()
        self.assertFalse(self.checker.timeout_occurred())


if __name__ == "__main__":  # pragma: no cover
    unittest.main(buffer=True)
