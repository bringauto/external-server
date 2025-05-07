# External Server

The External Server is a component of the [Fleet Protocol](https://github.com/bringauto/fleet-protocol). It communicates with an External Client, which is part of the [Module Gateway](https://gitlab.bringauto.com/bring-auto/fleet-protocol-v2/module-gateway).

It handles communication between a cloud instance and multiple cars registered under a single company.

# Requirements

- Python (version >= 3.10)

# Usage

## Install dependencies

### Submodules

First, update the [fleet protocol](https://github.com/bringauto/fleet-protocol) submodule

```bash
git submodule update --init lib/fleet-protocol
```

### Python packages

Install the required Python packages in a virtual environment by running the following (run pip3 install in the project root):

```bash
python3 -m venv .venv && \
source .venv/bin/activate && \
pip3 install -r requirements.txt
```

## Configure the External Server

Prepare your config file for the External Server. The config file can be found in `config/config.json`.

As an example of a filled-up config file, see the `config/config.json`. Before running the server, update the `config/config.json` accordingly.

### Server configuration

Set up the logging, the MQTT connection parameters and company name and the External server behavior.

- `logging` - contains the keys `console`and `file` for printing the logs into a console and a file, respectively. The `file` contains field `path` to set the (absolute or relative) path to the directory to store the logs. Both contain the following keys:
  - `level` - logging level as a string (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`). Case-insensitive.
  - `use` - set to `True` to allow to print the logs, otherwise set to `False`.
- `company_name` - used for MQTT topics name, should be same as in module gateway; only lowercase characters, numbers and underscores are allowed.
- `mqtt_address` - IP address of the MQTT broker.
- `mqtt_port` - port of the MQTT broker.
- `mqtt_timeout` (in seconds) - timeout for getting a message from MQTT Client.
- `timeout` (in seconds) - Maximum time amount between Status or Command messages and receiving corresponding responses.
- `send_invalid_command` - sends command to Module gateway even if External Server detects invalid command returned from external_server_api; affects only normal communication.
- `sleep_duration_after_connection_refused` - if the connection to Module Gateway was refused, the External Server will sleep for a defined duration before the next connection attempt proceeds.

### Common modules

One of the last items in the config file is `common_modules`, represented by key-value pairs. The key is the module ID (a module number), the value contains following

- `lib_path` (required) - path to module shared library (`*.so`).
- `config` (optional) - module specific configuration, any key-value pairs will be forwarded to module implementation init function. When empty or not provided, empty configuration is forwarded to the init function of module.
  > [!WARNING]
  > A common module will be used for all cars. No such module can be defined in the car configuration.
  > See the `config/config.json` for an example of modules configuration.

### Cars

The last item in the config file is `cars`, represented by key-value pairs. The key is the name of the car, the value is a dictionary containing car-specific modules keyed as `specific_modules`.

The structure of the `specific_modules` is the same as the `common_modules` structure.

See the `config/config.json` for an example of car configuration.

> [!WARNING]
> Configuring a module with the same ID both in `common_modules` and `specific_modules` is invalid and the server will not start.

> [!IMPORTANT]
> For each car, at least one module has to be defined, either in `common_modules` or `specific_modules`.

## Start the External Server

After configuration and installation of the dependencies, run External Server with this command:

```bash
python3 -m external_server <config> [--tls] [--ca <str>] [--cert <str>] [--key <str>]
```

- `<config>` = path to the config file
- `--tls` = tls mqtt authentication

Following arguments are used if argument `tls` is set:

- `--ca <str>` = path to ca certification
- `--cert <str>` = path to cert file
- `--key <str>` = path to key file

# Unit tests

## Necessary steps before testing

### Requirements

- [Requirements](#requirements)
- CMLIB: https://github.com/cmakelib/cmakelib

### Install the external server package

Do the steps from the [Install dependencies](#install-dependencies) section.

Install the package in editable mode and install test requirements (assuming you already installed the requirements for the server):

```bash
pip install -e .
pip install -r tests/requirements.txt
```

Update submodules

```bash
git submodule update --init --recursive
```

### Install the shared library

Compile a shared library for the [Example Module](https://github.com/bringauto/example-module/). This requires

- the [example-module](https://github.com/bringauto/example-module/) cloned as a submodule in the `tests/utils` directory.

Run the following

```bash
pushd tests/utils/example_module && \
mkdir -p _build && \
cd _build && \
cmake .. -DCMLIB_DIR=<path-to-cmakelib-dir> && \
make
popd
```

cmakelib directory is absolute path to this repo root directory.

## Running the tests

In the root folder, run the following

```bash
python -m tests [-h] [PATH1] [PATH2] ...
```

Each PATH is specified relative to the `tests` folder. If no PATH is specified, all the tests will run. Otherwise

- when PATH is a directory, the script will run all tests in this directory (and subdirectories),
- when PATH is a Python file, the script will run all tests in the file.

The `-h` flag makes the script display tests' coverage in an HTML format, for example in your web browser.

# Docker

The External Server is ready to use with Docker. You can build a Docker image with `docker build .` in this directory. The Dockerfile also describes compiling these Bringauto modules:

- module 1 - Mission module,
- module 2 - IO module.

These compiled modules are inserted into the image and are ready to use with the External Server in a Docker container.

The External Server can also be used with Docker Compose. In the `docker-compose.yml` is example of External Server service, which can't be used alone and should be inserted into another `docker-compose.yml` with MQTT service and defined network (the [etna](https://github.com/bringauto/etna) is an example). This specific example assumes that MQTT broker is service named `mosquitto` and defined network is `bring-emulator`.

# Development

## Type checking

To allow for type checking of the classes from compiler protobuf of Fleet Protocol, run:

```bash
pushd lib/fleet-protocol/protobuf && \
find ./definition -name "*.proto" -exec protoc -I=./definition --python_out=./compiled/python/build/lib/fleet_protocol_protobuf_files --pyi_out=./compiled/python/build/lib/fleet_protocol_protobuf_files {} +
popd
```

Then reinstall the requirements.
