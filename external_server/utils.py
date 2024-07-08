import argparse
import os.path
import threading

import InternalProtocol_pb2 as internal_protocol


def argparse_init() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-c", "--config", type=str, default="./config/config.json", help="path to the config file"
    )
    parser.add_argument("--tls", action=argparse.BooleanOptionalAction, help="tls authentication")
    tls = parser.add_argument_group("tls", description="if tls is used, set following arguments")
    tls.add_argument("--ca", type=str, help="path to ca certification")
    tls.add_argument("--cert", type=str, help="path to cert file")
    tls.add_argument("--key", type=str, help="path to key file")
    return parser.parse_args()


def check_file_exists(path: str) -> bool:
    return os.path.isfile(path)


def device_repr(device: internal_protocol.Device) -> str:
    return f"Device {device.module}/{device.deviceType}/{device.deviceRole}/{device.deviceName}"


class SingletonMeta(type):
    """
    This is a thread-safe implementation of Singleton.
    """

    _instances = {}
    _lock: threading.Lock = threading.Lock()

    def __call__(cls, *args, **kwargs):
        """
        Possible changes to the value of the `__init__` argument do not affect
        the returned instance.
        """
        with cls._lock:
            if cls not in cls._instances:
                instance = super().__call__(*args, **kwargs)
                cls._instances[cls] = instance
        return cls._instances[cls]
