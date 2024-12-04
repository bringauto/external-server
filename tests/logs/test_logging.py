import unittest
import json
import os

from external_server.logs import CarLogger, ESLogger, configure_logging, LOGGER_NAME
from external_server.config import LoggingConfig


PATH = os.path.dirname(os.path.dirname(__file__))


class Test_Server_Logger(unittest.TestCase):

    def setUp(self):
        self.config = LoggingConfig(
            console=LoggingConfig.HandlerConfig(level="debug", use=True),
            file=LoggingConfig.HandlerConfig(level="debug", use=False),
        )

    def test_logger(self):
        configure_logging(LOGGER_NAME, self.config)
        logger = ESLogger(LOGGER_NAME)
        with self.assertLogs(logger.logger, level="DEBUG") as cm:
            logger.debug("debug message")
            print(cm.output)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
