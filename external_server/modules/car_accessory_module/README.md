# Car Accessory Api
This project is a Proof of Concept. Car accessory API implements external_server_interface.

This application prints statuses given by forward_status() function. It also reads input from keyboard 
and when button given by config is read, it sends command PRESS to a connected device.

Device identification is saved when device_connected() is called. On device_disconnected() call, the application removes information about the device.
Only one connected device is supported.

To use this API, build it and include `libcar_accessory_api.so` to your project.

### Build
```
mkdir _build && cd _build
cmake ..
make
```

### Config
button = <command_key>
