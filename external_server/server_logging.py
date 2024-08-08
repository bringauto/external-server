import logging.config
import json


def global_config(config_file_path: str) -> None:
    """Configures the python logging module using the provided configuration file."""
    with open(config_file_path, "r") as f:
        logging.config.dictConfig(json.load(f))
