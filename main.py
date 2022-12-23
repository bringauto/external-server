#!/usr/bin/env python3

from module import argparse_init, Server


def main():
    args = argparse_init()
    server = Server(args.ip_address, args.port)
    server.init_mqtt_client()
    if args.tls:
        if args.ca is None or args.cert is None or args.key is None:
            print('TLS requires ca certificate, PEM encoded client certificate and private key to this certificate')
            exit(1)
        server.set_tls(args.ca, args.cert, args.key)

    try:
        server.start()
    except KeyboardInterrupt:
        server.stop()


if __name__ == '__main__':
    main()
