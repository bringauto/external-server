import argparse
import os.path
import sys
sys.path.append("lib/fleet-protocol/protobuf/compiled/python")

from InternalProtocol_pb2 import Device as _Device  # type: ignore


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


def device_repr(device: _Device) -> str:
    return f"Device {device.module}/{device.deviceType}/{device.deviceRole}/{device.deviceName}"

