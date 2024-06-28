import pytest
import time
import sys
sys.path.append("lib/fleet-protocol/protobuf/compiled/python")

from external_server.checker.order_checker import OrderChecker
import ExternalProtocol_pb2 as external_protocol

TIMEOUT = 1
SLEEP_TIME = TIMEOUT + 0.1


@pytest.fixture
def order_checker():
    order_checker = OrderChecker(Exception(), TIMEOUT)
    return order_checker


def test_check_status_message_with_counter_equal_to_current_counter(order_checker: OrderChecker):
    status_msg = external_protocol.Status()
    status_msg.messageCounter = order_checker.counter

    order_checker.check(status_msg)

    assert order_checker.missing_statuses.empty()
    assert order_checker.received_statuses.empty()
    assert not order_checker.checked_statuses.empty()
    assert order_checker.checked_statuses.get() == status_msg
    assert order_checker.counter == 2
    assert not order_checker.timeout.is_set()


def test_reset_order_checker_instance(order_checker: OrderChecker):
    status1 = external_protocol.Status()
    status1.messageCounter = 1
    order_checker.check(status1)

    status2 = external_protocol.Status()
    status2.messageCounter = 2
    order_checker.check(status2)

    order_checker.reset()

    assert order_checker.received_statuses.empty()
    assert order_checker.missing_statuses.empty()
    assert order_checker.checked_statuses.empty()
    assert not order_checker.timeout.is_set()
    assert order_checker.counter == 1


def test_message_less_counter_than_current_counter(order_checker: OrderChecker):
    status_msg = external_protocol.Status()
    status_msg.messageCounter = 0

    order_checker.check(status_msg)

    assert order_checker.missing_statuses.empty()
    assert order_checker.checked_statuses.empty()
    assert not order_checker.received_statuses.empty()
    assert not order_checker.timeout.is_set()
    assert order_checker.counter == 1


def test_message_greater_counter_than_current_counter(order_checker: OrderChecker):
    status_msg = external_protocol.Status()
    status_msg.messageCounter = 2

    order_checker.check(status_msg)

    assert not order_checker.missing_statuses.empty()
    assert order_checker.missing_statuses.queue[0][0] == 1
    assert order_checker.checked_statuses.empty()
    assert order_checker.counter == 1
    assert not order_checker.timeout.is_set()


def test_check_status_with_missing_messages(order_checker: OrderChecker):
    status_msg = external_protocol.Status()
    status_msg.messageCounter = order_checker.counter

    order_checker.check(status_msg)

    assert order_checker.missing_statuses.empty()
    assert order_checker.received_statuses.empty()
    assert not order_checker.checked_statuses.empty()
    assert order_checker.checked_statuses.queue[0] == status_msg
    assert order_checker.get_status() is not None

    order_checker.reset()

    assert order_checker.missing_statuses.empty()
    assert order_checker.received_statuses.empty()
    assert order_checker.checked_statuses.empty()
    assert not order_checker.timeout.is_set()
    assert order_checker.counter == 1


def test_multiple_status_messages_out_of_order(order_checker: OrderChecker):
    status_msg1 = external_protocol.Status()
    status_msg1.messageCounter = 3

    status_msg2 = external_protocol.Status()
    status_msg2.messageCounter = 1

    status_msg3 = external_protocol.Status()
    status_msg3.messageCounter = 2

    order_checker.check(status_msg1)
    order_checker.check(status_msg2)
    order_checker.check(status_msg3)

    assert order_checker.get_status().messageCounter == 1
    assert order_checker.get_status().messageCounter == 2
    assert order_checker.get_status().messageCounter == 3


# Receive status messages in sequential order
def test_receive_status_messages_sequential_order(order_checker: OrderChecker):
    status1 = external_protocol.Status(messageCounter=1)
    status2 = external_protocol.Status(messageCounter=2)
    status3 = external_protocol.Status(messageCounter=3)

    order_checker.check(status1)
    order_checker.check(status2)
    order_checker.check(status3)

    assert order_checker.get_status() == status1
    assert order_checker.get_status() == status2
    assert order_checker.get_status() == status3
    assert order_checker.get_status() is None


# Receive status messages out of order, but eventually receive all messages
def test_receive_status_messages_out_of_order_but_received_all(order_checker: OrderChecker):
    status1 = external_protocol.Status(messageCounter=1)
    status2 = external_protocol.Status(messageCounter=2)
    status3 = external_protocol.Status(messageCounter=3)

    order_checker.check(status2)
    order_checker.check(status3)
    order_checker.check(status1)

    assert order_checker.get_status() == status1
    assert order_checker.get_status() == status2
    assert order_checker.get_status() == status3
    assert order_checker.get_status() is None


# Receive status messages out of order and not received all
def test_receive_status_messages_out_of_order_not_received_all(order_checker: OrderChecker):
    status2 = external_protocol.Status(messageCounter=2)
    status3 = external_protocol.Status(messageCounter=3)

    order_checker.check(status2)
    order_checker.check(status3)

    assert order_checker.get_status() is None


# Reset the checker after receiving all messages
def test_reset_checker(order_checker: OrderChecker):
    status1 = external_protocol.Status(messageCounter=1)
    status2 = external_protocol.Status(messageCounter=2)
    status3 = external_protocol.Status(messageCounter=3)

    order_checker.check(status1)
    order_checker.check(status2)
    order_checker.check(status3)

    order_checker.reset()

    assert order_checker.get_status() is None


# Receive status messages with counter starting from a number different than 1
def test_receive_status_messages_starting_from_different_number_than_1(order_checker: OrderChecker):
    status1 = external_protocol.Status(messageCounter=2)
    status2 = external_protocol.Status(messageCounter=3)
    status3 = external_protocol.Status(messageCounter=4)

    order_checker.check(status1)
    order_checker.check(status2)
    order_checker.check(status3)

    assert order_checker.get_status() is None


# Check statuses in wrong order and waiting for Checker timeout
def test_wait_for_timeout(order_checker: OrderChecker):
    status1 = external_protocol.Status(messageCounter=1)
    status3 = external_protocol.Status(messageCounter=3)

    order_checker.check(status1)
    order_checker.check(status3)
    time.sleep(SLEEP_TIME)

    with pytest.raises(Exception):
        order_checker.check_time_out()


# Check statuses in wrong order, reset the OrderChecker and waiting for Checker timeout
def test_wait_for_timeout_after_reset(order_checker: OrderChecker):
    status1 = external_protocol.Status(messageCounter=1)
    status3 = external_protocol.Status(messageCounter=3)

    order_checker.check(status1)
    order_checker.check(status3)
    order_checker.reset()

    time.sleep(SLEEP_TIME)

    order_checker.check_time_out()
