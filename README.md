# External Server

This directory contains a fake external server that communicates with an external client, which is part of the [Module Gateway](https://gitlab.bringauto.com/bring-auto/fleet-protocol-v2/module-gateway).

# Fleet protocol deviations

This implementation of the External Server can handle only one car. To handle multiple cars, more instances of this External Server must be created. This is a deviation from Fleet protocol where one External Server instance can handle multiple cars.

# Requirements

- Python (version >= 3.10)

# Usage

## Install dependencies

### Python packages

Install the required Python packages in virtual environment by running the following

```bash
python3 -m venv .venv && \
source .venv/bin/activate && \
pip3 install -r requirements.txt
```

### Submodules

Update the [fleet protocol](https://github.com/bringauto/fleet-protocol) submodule and compile the protobuf

```bash
git submodule update lib/fleet-protocol && \
pushd lib/fleet-protocol/protobuf && \
find ./definition -name "*.proto" -exec protoc -I=./definition --python_out=./compiled/python --pyi_out=./compiled/python {} +
popd
```

## Configure the External Server

Prepare your config file for the External Server. The config file can be found in `config/config.json`.

As an example of a filled-up config file, see the `config/config.json.example`. When using the modified `config/config.json.example`, remove the `example` suffix from the file name.

### Server configuration

Set up the MQTT connection parameters, company and car name and the External server behavior.

- `company_name`, `car_name` (required) - used for MQTT topics name, should be same as in module gateway; only lowercase characters, numbers and underscores are allowed.
- `mqtt_address` (required) - IP address of the MQTT broker.
- `mqtt_port` (required) - port of the MQTT broker.
- `mqtt_timeout` (in seconds) - timeout for getting a message from MQTT Client.
- `timeout` (in seconds) - Maximum time amount between Status and Command messages.
- `send_invalid_command` - sends command to Module gateway even if External Server detects invalid command returned from external_server_api; affects only normal communication.
- `sleep_duration_after_connection_refused` - if the connection to Module Gateway was refused, the External Server will sleep for a defined duration before the next connection attempt proceeds.
- `log_files_directory` (required) - path to a directory in which the logs will be stored. If left empty, the current working directory will be used.
- `log_files_to_keep` (required) - number of log files that will be kept (can be 0).
- `log_file_max_size_bytes` (required) - max file size of a log in bytes (0 means unlimited).

### Modules

The last item in the config file is `modules`, represented by key-value pairs. The key is the ID of the module, the value contains following

- `lib_path` (required) - path to module shared library (`*.so`).
- `config` (optional) - specification of config for the module, any key-value pairs will be forwarded to module implementation init function; when empty or missing, empty config forwarded to init function.

See the `config/config.json.example` for an example of modules configuration.

## Start the External Server

After configuration and installation of the dependencies, run External Server with this command:

```bash
python3 external_server_main.py --config <str> [--tls] [--ca <str>] [--cert <str>] [--key <str>]
```

- `-c or --config <str>` = path to the config file, default = `./config/config.json`
- `--tls` = tls mqtt authentication

Following arguments are used if argument `tls` is set:

- `--ca <str>` = path to ca certification
- `--cert <str>` = path to cert file"
- `--key <str>` = path to key file

# Unit tests

## Necessary steps before testing

First, do the steps from the [Install dependencies](#install-dependencies) section.

The proceed with the following steps.

### Install the external server package

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

- the CMakelib installed (see [here](https://github.com/cmakelib/cmakelib)) and the `CMLIB_DIR` env variable set to the installation directory and exported,
- the [example-module](https://github.com/bringauto/example-module/) cloned as a submodule in the `tests/utils` directory.

Run the following in the `tests/utils/example_module` directory

```bash
pushd tests/utils/example_module && \
if [ ! -d "_build" ]; then mkdir _build; fi && \
cd _build && \
cmake .. -DCMLIB_DIR=https://github.com/cmakelib/cmakelib && \
make
popd
```

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

The External Server is ready to use with Docker. You can build Docker image with `docker build .` in this directory. The Dockerfile also describes compiling these Bringauto modules:

- module 1 - Mission module
- module 2 - IO module

These compiled modules are inserted into image and are ready to use with External Server in Docker container.

The External Server can be also used with docker compose. In the `docker-compose.yml` is example of External Server service, which can't be used alone and should be inserted into another `docker-compose.yml` with MQTT service and defined network (the [etna](https://github.com/bringauto/etna) is an example). This specific example assumes that MQTT broker is service named `mosquitto` and defined network is `bring-emulator`.

# Development

## Type checking

To allow for type checking of the classes from compiler protobuf of fleet protocol, add `<project-root-directory>/lib/fleet-protocol/protobuf/compiled/python`to the `PYTHONPATH` environment variable.
