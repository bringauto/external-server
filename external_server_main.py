#!/usr/bin/env python3
import logging
import logging.handlers
import sys
import os

from rich.logging import RichHandler

dir_path = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(dir_path, "./lib/fleet-protocol/protobuf/compiled/python"))

from external_server.utils import argparse_init
from external_server.external_server import ExternalServer
from external_server.config import load_config, InvalidConfigError
from external_server import constants


def main() -> None:
    """Main entry of external server"""
    args = argparse_init()
    try:
        config = load_config(args.config)
    except InvalidConfigError as exc:
        print(f"Invalid config: {exc}")
        sys.exit(1)

    if (config.log_files_to_keep):
            file_handler = logging.handlers.RotatingFileHandler(
                filename=str(config.log_files_directory) + "/" + constants.LOG_FILE_NAME,
                maxBytes=config.log_file_max_size_bytes,
                backupCount=config.log_files_to_keep - 1
            )
            file_handler.setFormatter(logging.Formatter(constants.LOG_FORMAT))
            logging.basicConfig(
                level=logging.INFO,
                format="%(name)s: %(message)s",
                datefmt="[%X]",
                handlers=[RichHandler(), file_handler],
            )
    else:
        logging.basicConfig(
        level=logging.INFO,
        format="%(name)s: %(message)s",
        datefmt="[%X]",
        handlers=[RichHandler()],
    )
        
    logger = logging.getLogger("Main")
    logger.info(f"Loaded config:\n{config.get_config_dump_string()}")

    server = ExternalServer(config)
    if args.tls:
        if args.ca is None or args.cert is None or args.key is None:
            logger.error(
                "TLS requires ca certificate, PEM encoded client certificate and private key to this certificate"
            )
            sys.exit(1)
        server.set_tls(args.ca, args.cert, args.key)

    try:
        server.start()
    except KeyboardInterrupt:
        server.stop()


if __name__ == "__main__":
    main()
