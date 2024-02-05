#!/usr/bin/env python3
import logging
import json
import sys

from rich.logging import RichHandler

from external_server.utils import argparse_init
from external_server.external_server import ExternalServer
from external_server.config import Config, load_config, InvalidConfigError


def main() -> None:
    """Main entry of external server"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(name)s: %(message)s",
        datefmt="[%X]",
        handlers=[RichHandler()],
    )
    logger = logging.getLogger("Main")
    args = argparse_init()
    try:
        config = load_config(args.config)
    except InvalidConfigError as exc:
        logger.error(f"Invalid config: {exc}")
        sys.exit(1)

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
