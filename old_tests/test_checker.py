import pytest

from external_server.checker.checker import Checker


class TestChecker:
    def test_check_time_out_raises_exception_if_timeout_occurred(self):
        exc = Exception("Timeout occurred")
        checker = Checker(exc)
        checker._set_time_out()
        with pytest.raises(Exception):
            checker.check_time_out()

    def test_check_time_out_does_not_raise_exception_if_timeout_did_not_occur(self):
        exc = Exception("Timeout occurred")
        checker = Checker(exc)
        checker.check_time_out()

    def test_set_time_out_sets_timeout_event(self):
        exc = Exception("Timeout occurred")
        checker = Checker(exc)
        checker._set_time_out()
        assert checker.time_out.is_set()
