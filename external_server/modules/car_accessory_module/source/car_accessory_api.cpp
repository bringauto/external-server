#include <thread>
#include <iostream>
#include <atomic>

#include <CarAccessoryModule.pb.h>
#include <external_server_interface.h>

struct context {
	char button {};
	std::vector<struct device_identification> devices;
	command_forwarder forwardCommand { nullptr };
	std::atomic<bool> stopThread;
};

void listenKeyboard(struct context *context, void *external_server_context) {
	char b;

	auto command = CarAccessoryModule::ButtonCommand();
	command.set_command(CarAccessoryModule::ButtonCommand_Command::ButtonCommand_Command_PRESS);

	struct buffer commandData {};
	commandData.size = command.ByteSizeLong();
	commandData.data = malloc(commandData.size);
	if(commandData.data == nullptr) {
		printf("[Car Accessory Module][ERROR]: Memory allocation error\n");
	}
	command.SerializeToArray(commandData.data, commandData.size);
	while(!context->stopThread) {
		std::cin >> b;
		if(b == context->button) {
			for(auto device : context->devices) {
				context->forwardCommand(commandData, device, external_server_context);
			}
		}
	}
	free(commandData.data);
}

void *init(key_getter get_key, void *external_server_context) {
	char *button = get_key("button", external_server_context);
	if(button == nullptr) {
		printf("[Car Accessory Module][ERROR]: Invalid value for argument button\n");
		return nullptr;
	}
	auto *contextPtr = new context;

	contextPtr->stopThread = false;
	contextPtr->button = button[0];
	return contextPtr;
}

int destroy(void **context) {
	if(context == nullptr) {
		return -1;
	}
	auto con = (struct context *)context;
	con->stopThread = true;
	delete *context;
	context = nullptr;
	return 0;
}

int register_command_callback(command_forwarder forward_command, void *context, void *external_server_context) {
	if(context == nullptr) {
		return -1;
	}
	auto con = (struct context *)context;
	con->forwardCommand = forward_command;
	std::thread keyboardListener(listenKeyboard, con, external_server_context);
	keyboardListener.detach();
	return 0;
}

int forward_status(const struct buffer device_status, const struct device_identification device, void *context) {
	CarAccessoryModule::ButtonStatus status;
	status.ParseFromArray(device_status.data, device_status.size);
	printf("[Car Accessory Module][INFO]: Received status from: %s/%s. Is pressed: %s\n", device.device_role,
		   device.device_name, status.ispressed() ? "true" : "false");
	return 0;
}

int forward_error_message(const struct buffer error_msg, const struct device_identification device, void *context) {
	CarAccessoryModule::ButtonError buttonError;
	buttonError.ParseFromArray(error_msg.data, error_msg.size);
	printf("[Car Accessory Module][INFO]: Received error message from: %s/%s. Press count: %d\n",
		   device.device_role, device.device_name, buttonError.presscount());
	return 0;
}

int command_ack(const struct buffer command, const void *context) {
	printf("[Car Accessory Module][INFO]: Command was successfully delivered");
	return 0;
}

int get_module_number() {
	return 2; 	/// Based on module number form .proto file
}

int device_connected(const struct device_identification device, void *context) {
	auto con = (struct context *)context;
	struct device_identification newDevice = {device.device_type}; //, memcpy(device.device_role), device.device_name};
	strcpy(newDevice.device_role, device.device_role );
	strcpy(newDevice.device_name, device.device_name );
	con->devices.emplace_back(newDevice);
	return 0; // TODO deep copy a pridat do vectoru
}

int device_disconnected(const disconnect_types disconnectType, const struct device_identification device, void *context) {
	switch(disconnectType) {
		case announced:
			printf("[Car Accessory Module][INFO]: Device disconnected %s/%s\n", device.device_role, device.device_name);
			break;
		case timeout:
			printf("[Car Accessory Module][WARNING]: Device timeout %s/%s\n", device.device_role, device.device_name);
			break;
		case error:
			printf("[Car Accessory Module][ERROR]: Device error. Disconnected %s/%s\n", device.device_role,
				   device.device_name);
			break;
	}
	auto con = (struct context *)context; //TODO odstranit z vektoru

	for (auto it = con->devices.begin(); it != con->devices.end();) {
		if (it->device_type == device.device_type && strcmp(it->device_role, device.device_role) == 0
			&& strcmp(it->device_name, device.device_name) == 0) {
			con->devices.erase(it);
			return 0;
		}
	}
	return -3;
}
