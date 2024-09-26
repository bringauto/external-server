#!/usr/bin/env python3
import sys
import argparse
import os
import json

from external_server.server import ExternalServer, eslogger as eslogger
from external_server.config import load_config, InvalidConfiguration
from external_server.logs import configure_logging


def parsed_script_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-c",
        "--config",
        type=str,
        default="./config/config.json",
        help="path to the configuration file",
    )
    parser.add_argument("--tls", action=argparse.BooleanOptionalAction, help="tls authentication")
    tls = parser.add_argument_group("tls", description="if tls is used, set following arguments")
    tls.add_argument("--ca", type=str, help="path to Certificate Authority certificate files")
    tls.add_argument("--cert", type=str, help="path to PEM encoded client certificate file")
    tls.add_argument("--key", type=str, help="path to PEM encoded client private keys file")

    args = parser.parse_args()

    if not os.path.isfile(args.config):
        raise FileNotFoundError(f"Config file {os.path.abspath(args.config)} not found.")
    if args.tls:
        missing_fields = []
        if not args.ca:
            missing_fields.append("ca certificate")
        if not args.cert:
            missing_fields.append("PEM encoded client certificate")
        if not args.key:
            missing_fields.append("private key to PEM encoded client certificate")
        if missing_fields:
            e = argparse.ArgumentError(
                None, f"TLS requires additional parameters. The following is missing: {', '.join(missing_fields)}"
            )
            raise e
    return args


def main() -> None:
    """Main entry of external server"""
    try:
        args = parsed_script_args()
    except argparse.ArgumentError as exc:
        eslogger.error(f"Invalid arguments. {exc}")
        print(f"Invalid arguments. {exc}")
        sys.exit(1)

    try:
        with open(args.config) as f:
            config_dict = json.loads(f.read())
            config = load_config(args.config)
            configure_logging("External Server", config_dict)
    except InvalidConfiguration as exc:
        eslogger.error(f"Invalid config: {exc}")
        print(f"Invalid config: {exc}")
        sys.exit(1)

    eslogger.info(f"Loaded config:\n{config.get_config_dump_string()}")
    server = ExternalServer(config)
    if args.tls:
        if args.ca is None or args.cert is None or args.key is None:
            eslogger.error(
                "TLS requires ca certificate, PEM encoded client certificate and private key to this certificate"
            )
            sys.exit(1)
        server.tls_set(args.ca, args.cert, args.key)

    try:
        server.start()
    except KeyboardInterrupt:
        server.stop(reason="keyboard interrupt")


if __name__ == "__main__":
    main()
