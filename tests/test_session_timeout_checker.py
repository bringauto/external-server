import time
import pytest
import sys

sys.path.append("lib/fleet-protocol/protobuf/compiled/python")

from external_server.checker.session_timeout_checker import SessionTimeoutChecker


class TestException(Exception):
    __test__ = False


class TestSessionTimeoutChecker:
    TIMEOUT = 1
    SLEEP_TIME = TIMEOUT + 0.1

    def test_start_then_stop_and_wait_for_timeout(self):
        checker = SessionTimeoutChecker(TestException(), self.TIMEOUT)

        checker.start()
        checker.stop()

        time.sleep(self.SLEEP_TIME)
        checker.check_time_out()

    def test_start_and_wait_for_timeout(self):
        checker = SessionTimeoutChecker(TestException(), self.TIMEOUT)

        checker.start()
        time.sleep(self.SLEEP_TIME)

        with pytest.raises(TestException):
            checker.check_time_out()

    def test_start_reset_and_wait_for_timeout_(self):
        checker = SessionTimeoutChecker(TestException(), self.TIMEOUT)

        checker.start()
        checker.reset()
        time.sleep(self.SLEEP_TIME)

        with pytest.raises(TestException):
            checker.check_time_out()

    def test_stop_before_start(self):
        checker = SessionTimeoutChecker(TestException(), self.TIMEOUT)

        checker.stop()
