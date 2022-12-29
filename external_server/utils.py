import argparse
import os.path


def argparse_init() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument('-i', '--ip-address', type=str,
                        default='127.0.0.1', help='ip address of the MQTT server')
    parser.add_argument('-p', '--port', type=int, default=1883,
                        help='port of the MQTT server')
    parser.add_argument('--tls', action=argparse.BooleanOptionalAction, help='Tls authentication')
    parser.add_argument('--ca', type=str, help='path to ca certification, used if tls is set')
    parser.add_argument('--cert', type=str, help='path to cert file, used if tls is set')
    parser.add_argument('--key', type=str, help='path to key file, used if tls is set')
    return parser.parse_args()


def check_file_exists(path: str) -> bool:
    return os.path.isfile(path)
