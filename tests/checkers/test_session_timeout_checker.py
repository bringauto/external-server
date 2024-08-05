import unittest
import time
import sys
sys.path.append("lib/fleet-protocol/protobuf/compiled/python")

from external_server.checkers.session import Session


_CHECKER_TIMEOUT = 0.05


class Test_Setting_Timeout(unittest.TestCase):

    def test_started_checker_does_set_timeout(self):
        session = Session(_CHECKER_TIMEOUT)
        session.start()
        time.sleep(_CHECKER_TIMEOUT+0.001)
        self.assertTrue(session.timeout_event.is_set())

    def test_starting_checker_again_has_no_effect(self):
        session = Session(_CHECKER_TIMEOUT)
        session.start()
        time.sleep(_CHECKER_TIMEOUT/2)
        session.start()
        time.sleep(_CHECKER_TIMEOUT/2+.001)
        self.assertTrue(session.timeout_event.is_set())

    def test_stopped_checker_does_not_set_timeout(self):
        session = Session(_CHECKER_TIMEOUT)
        session.start()
        session.stop()
        time.sleep(_CHECKER_TIMEOUT + 0.01)
        self.assertFalse(session.timeout_event.is_set())

    def test_stopping_checker_after_timeout_unsets_the_timeout(self):
        session = Session(_CHECKER_TIMEOUT)
        session.start()
        time.sleep(_CHECKER_TIMEOUT + 0.01)
        self.assertTrue(session.timeout_event.is_set())
        session.stop()
        self.assertFalse(session.timeout_event.is_set())

    def test_restarting_checker_postpones_setting_timeout(self):
        session = Session(_CHECKER_TIMEOUT)
        session.start()
        time.sleep(_CHECKER_TIMEOUT/2)
        session.reset_timer()
        time.sleep(_CHECKER_TIMEOUT/2)
        self.assertFalse(session.timeout_event.is_set())
        time.sleep(_CHECKER_TIMEOUT/2+.001)
        self.assertTrue(session.timeout_event.is_set())


if __name__ == "__main__":  # pragma: no cover
    unittest.main(buffer=True)
