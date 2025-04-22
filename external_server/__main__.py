import sys
import argparse
import os

from external_server.server.all_cars import ExternalServer, logger
from external_server.config import load_config, InvalidConfiguration
from external_server.logs import configure_logging


def parsed_script_args() -> tuple[argparse.Namespace, str]:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "<config-file-path>",
        type=str,
        default="./config/config.json",
        help="path to the configuration file",
    )
    parser.add_argument(
        "--tls", action=argparse.BooleanOptionalAction, help="use tls authentication"
    )
    tls = parser.add_argument_group("tls", description="if tls is used, set following arguments")
    tls.add_argument("--ca", type=str, help="path to Certificate Authority certificate files")
    tls.add_argument("--cert", type=str, help="path to PEM encoded client certificate file")
    tls.add_argument("--key", type=str, help="path to PEM encoded client private keys file")

    args = parser.parse_args()

    config_path = args.__dict__.pop("<config-file-path>")
    if not os.path.isfile(config_path):
        raise FileNotFoundError(f"Config file {os.path.abspath(config_path)} not found.")
    if args.tls:
        missing_fields = []
        if not args.ca:
            missing_fields.append("ca certificate (--ca)")
        if not args.cert:
            missing_fields.append("PEM encoded client certificate (--cert)")
        if not args.key:
            missing_fields.append("private key to PEM encoded client certificate (--key)")
        if missing_fields:
            raise argparse.ArgumentError(
                None, f"TLS requires additional parameters: {', '.join(missing_fields)}"
            )
    return args, config_path


def main() -> None:
    """Main entry of external server"""
    try:
        args, config_path = parsed_script_args()
    except argparse.ArgumentError as exc:
        logger.error(f"Invalid arguments. {exc}")
        print(f"Invalid arguments. {exc}")
        sys.exit(1)

    try:
        config = load_config(config_path)
        configure_logging("External Server", config.logging)
    except InvalidConfiguration as exc:
        logger.error(f"Invalid config: {exc}")
        print(f"Invalid config: {exc}")
        sys.exit(1)

    logger.info(f"Loaded config:\n{config.model_dump_json(indent=4)}")
    server = ExternalServer(config)
    if args.tls:
        server.set_tls(args.ca, args.cert, args.key)

    try:
        server.start(wait_for_join=True)
    except KeyboardInterrupt:
        server.stop(reason="keyboard interrupt")


if __name__ == "__main__":
    main()
