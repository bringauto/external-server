import argparse
import os.path


def argparse_init() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument('-i', '--ip-address', type=str,
                        default='127.0.0.1', help='ip address of the MQTT broker')
    parser.add_argument('-p', '--port', type=int, default=1883,
                        help='port of the MQTT broker')
    parser.add_argument('--tls', action=argparse.BooleanOptionalAction, help='Tls authentication')
    tls = parser.add_argument_group('tls', description='if tls is used, set following arguments')
    tls.add_argument('--ca', type=str, help='path to ca certification')
    tls.add_argument('--cert', type=str, help='path to cert file')
    tls.add_argument('--key', type=str, help='path to key file')
    return parser.parse_args()


def check_file_exists(path: str) -> bool:
    return os.path.isfile(path)
