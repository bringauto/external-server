# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

The External Server is a component of the BringAuto Fleet Protocol that handles communication between a cloud instance and multiple cars. It bridges External Clients (Module Gateway) with car modules via MQTT and dynamically loaded shared libraries.

## Common Commands

### Setup
```bash
git submodule update --init --recursive
python3 -m venv .venv && source .venv/bin/activate
pip3 install -r requirements.txt
pip install -e .
```

### Run Server
```bash
python3 -m external_server <config-path> [--tls] [--ca <path>] [--cert <path>] [--key <path>]
```

### Build Standalone Package (.pyz)
```bash
pip install shiv
shiv -e external_server.__main__:main -o external_server.pyz . -r requirements.txt --compressed
```

### Run Tests
```bash
pip install -r tests/requirements.txt
python -m tests                           # all tests
python -m tests server/                   # specific directory
python -m tests api_access/test_api.py   # specific file
python -m tests -h                        # with HTML coverage report
```

### Build Example Module (required for tests)
```bash
pushd tests/utils/example_module && mkdir -p _build && cd _build && \
cmake .. -DCMLIB_DIR=<path-to-cmakelib-dir> && make && popd
```

### Regenerate Protobuf Type Stubs
```bash
pushd lib/fleet-protocol/protobuf && \
find ./definition -name "*.proto" -exec protoc -I=./definition \
  --python_out=./compiled/python/fleet_protocol_protobuf_files \
  --pyi_out=./compiled/python/fleet_protocol_protobuf_files {} + && popd
```

## Architecture

### Threading Model
- `ExternalServer` (all_cars.py) spawns one `CarServer` thread per configured car
- Each `CarServer` (single_car.py) operates independently with its own MQTT connection and modules

### State Machine (CarServer)
`UNINITIALIZED → CONNECTED → INITIALIZED → RUNNING → STOPPED/ERROR`

### Component Layers
```
ExternalServer
└── CarServer (per car)
    ├── MQTTClientAdapter - Paho MQTT client wrapper (QoS 1, 15s keepalive)
    ├── EventQueue - Thread-safe event synchronization
    ├── StatusChecker / CommandChecker - Message validation
    └── ServerModule (per module ID)
        ├── APIClientAdapter - Loads .so libraries via ctypes
        └── CommandWaitingThread - Async command handling
```

### Key Directories
- `external_server/server/` - Core server logic (CarServer, ExternalServer)
- `external_server/adapters/mqtt/` - MQTT communication
- `external_server/adapters/api/` - C library interface via ctypes
- `external_server/checkers/` - Message validation and timeout handling
- `external_server/models/` - Data structures, events, exceptions

### Protocol
- Uses Fleet Protocol (Protobuf-based) over MQTT
- Protobuf definitions in `lib/fleet-protocol/` submodule
- Generated Python files in `lib/fleet-protocol/protobuf/compiled/python/`

## Configuration

Config file (`config/config.json`) defines:
- `company_name` - MQTT topic prefix (lowercase, numbers, underscores only)
- `mqtt_address`, `mqtt_port` - Broker connection
- `mqtt_timeout`, `timeout` - Message timeouts in seconds
- `common_modules` - Modules shared by all cars (keyed by module ID)
- `cars` - Per-car config with `specific_modules`

Module IDs must be unique within each car (no overlap between common and specific).
