# External Server

Directory contains fake external server the communicates with external client, which is part of the [module gateway](https://gitlab.bringauto.com/bring-auto/fleet-protocol-v2/module-gateway).

## Requirements

- Python (version >= 3.10)
- Other requirements can be installed by `pip3 install -r requirements.txt`

## Arguments

- `-i or --ip-address <str>` = ip address of the module gateway, default = `127.0.0.1`
- `-p or --port <int>` = port of the module gateway, default = `1883`
- `--tls` = tls mqtt authentication

### TLS arguments

following arguments are used if argument `tls` is set:

- `--ca <str>` = path to ca certificatione
- `--cert <str>` = path to cert file
- `--key <str>` = path to key file

## Run
```
python3 main.py
```
