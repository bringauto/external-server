# External Server

This directory contains a fake external server that communicates with an external client, which is part of the [module gateway](https://gitlab.bringauto.com/bring-auto/fleet-protocol-v2/module-gateway).

## Fleet protocol deviations
- This implementation of the External Server can handle only one car. To handle multiple cars, more instances of this External Server must be created. This is a deviation from Fleet protocol where one External Server instance can handle multiple cars.

## Requirements

- Python (version >= 3.10)
- Other Python requirements can be installed by `pip3 install -r requirements.txt`

## Arguments

- `-c or --config <str>` = path to the config file, default = `./config/config.json`
- `--tls` = tls mqtt authentication

### TLS arguments

following arguments are used if argument `tls` is set:

- `--ca <str>` = path to ca certification
- `--cert <str>` = path to cert file
- `--key <str>` = path to key file

## Usage

Prepare your shared library of module implementation (implementation of external_server_api.h). To use this library with External Server, you need to fill the module IDand path to this library into the External Server config file.

### Options in the config file

 - company_name, car_name (required) - used for MQTT topics name, should be same as in module gateway; only lowercase characters, numbers and underscores are allowed
 - mqtt_address (required) - IP address of the MQTT broker
 - mqtt_port (required) - port of the MQTT broker
 - mqtt_timeout (in seconds) - timeout for getting a message from MQTT Client
 - timeout (in seconds) - Maximum time amount between Status and Command messages
 - send_invalid_command - sends command to Module gateway even if External Server detects invalid command returned from external_server_api; affects only normal communication
 - sleep_duration_after_connection_refused - if the connection to Module Gateway was refused, the External Server will sleep for a defined duration before the next connection attempt proceeds.
 - log_files_directory (required) - path to a directory in which the logs will be stored. If left empty, the current working directory will be used
 - log_files_to_keep (required) - number of log files that will be kept (can be 0)
 - log_file_max_size_bytes (required) - max file size of a log in bytes (0 means unlimited)
 - modules (required) - supported modules specified by module number
    - lib_path (required) - path to module shared library
    - config (optional) - specification of config for the module, any key-value pairs will be forwarded to module implementation init function; when empty or missing, empty config forwarded to init function

 ### Example of config file
After filling in the config, you can run External Server with this command:

```bash
python3 external_server_main.py
```

# Testing

## Unit tests

### Necessary steps before testing

#### Install the external server package

Install the package in editable mode by running the following in the root directory:
```bash
pip install -e .
```

#### Install the shared library

to be able to run tests for the External Server API client, you need to compile a shared library for the [Example Module](https://github.com/bringauto/example-module/). To be able to do so, you need to have
- the CMakelib installed (see [here](https://github.com/cmakelib/cmakelib)) and the `CMLIB_DIR` environment variable set to the directory and exported (see the instructions in the CMakelib README),
- the [example-module](https://github.com/bringauto/example-module/) cloned as a submodule in the `tests/utils` directory.

Run the following in the `tests/utils/example-module` directory.
```bash
mkdir _build && cd _build
cmake .. -DCMLIB_DIR=<github-url-to-cmakelib-repository-root-dir>
make
```


### Running the tests

In the root folder, run the following
```bash
python -m tests [-h] [PATH1] [PATH2] ...
```

Each PATH is specified relative to the `tests` folder. If no PATH is specified, all the tests will run. Otherwise
- when PATH is a directory, the script will run all tests in this directory (and subdirectories),
- when PATH is a Python file, the script will run all tests in the file.

The `-h` flag makes the script display tests' coverage in an HTML format, for example in your web browser.


# Docker
The External Server is ready to use with docker. You can build docker image with `docker build .` in this directory. The Dockerfile also describes compiling these Bringauto modules:
 - module 3 - IO module

These compiled modules are inserted into image and are ready to use with External Server in docker container.

The External Server can be also used with docker compose. In the docker-compose.yml is example of External Server service, which can't be used alone and should be inserted into another docker-compose.yml with MQTT service and defined network. This specific example assumes that MQTT broker is service named `mosquitto` and defined network is `bring-emulator`.
