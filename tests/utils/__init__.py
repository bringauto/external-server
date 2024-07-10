import os as _os

from tests.utils._mqtt_broker_test import MQTTBrokerTest
from tests.utils._threads import ExternalServerThreadExecutor


EXAMPLE_MODULE_SO_LIB_PATH = \
    _os.path.abspath("tests/utils/example_module/_build/libexample-external-server-sharedd.so")
