#include <thread>
#include <iostream>
#include <atomic>

#include <CarAccessoryModule.pb.h>
#include <external_server_interface.h>

struct context {
	std::vector<struct device_identification> devices;
	std::vector<std::tuple<CarAccessoryModule::ButtonCommand, struct device_identification>> commandVector;
	std::atomic<bool> stopThread;
};

void listenKeyboard(struct context *context, char button) {
	char inputChar;

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
		std::cin >> inputChar;
		if(inputChar == button) {
			for(auto device : context->devices) {
				std::cout << "1230";
//				context->commandVector.push_back(std::make_tuple(commandData, device));
			}
			// TODO notify
		}
	}
	free(commandData.data);
}

void *init(struct config config_data) {
	if(config_data.size > 0 && strcmp((char *)config_data.parameters[0].key.data, "button") == 0) {
		char button[config_data.parameters[0].value.size];
		strcpy(button, (char *)config_data.parameters[0].value.data);

		auto *contextPtr = new context;

		contextPtr->stopThread = false;

		std::thread keyboardListener(listenKeyboard, contextPtr, button[0]);
		keyboardListener.detach();

		return contextPtr;
	} else {
		return nullptr;
	}
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

int wait_for_command(int timeout_time_in_ms) {
	return 0; // TODO
}

int get_command(buffer* command, device_identification* device) {
	return 0; // TODO
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
	if (context == nullptr) {
		return -1;
	}
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
