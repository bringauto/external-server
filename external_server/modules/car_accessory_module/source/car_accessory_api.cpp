#include <thread>
#include <iostream>
#include <atomic>

#include <proto/CarAccessoryModule.pb.h>



extern "C" {
#include "external_server_interface.h"
}

struct context {
	char button;
	struct device_identification device;
	command_forwarder forwardCommand = nullptr;
	std::thread listenThread;
	std::atomic<bool> stopThread;
};

void listenKeyboard(const struct context *context) {
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
			context->forwardCommand(commandData, context->device);
		}
	}
	free(commandData.data);
}

void *init(key_getter get_key) {
	char *button = reinterpret_cast<char *>(get_key("button"));
	if(button == nullptr) {
		printf("[Car Accessory Module][ERROR]: Invalid value for argument button\n");
		return nullptr;
	}
	auto *context = (struct context *)(malloc(sizeof(struct context)));
	if(context == nullptr) {
		printf("[Car Accessory Module][ERROR]: Memory allocation error\n");
		return nullptr;
	}
	context->stopThread = false;
	context->button = button[0];
	return context;
}

int destroy(void **context) {
	if(context == nullptr) {
		return -1;
	}
	auto con = (struct context *)context;
	con->stopThread = true;
	con->listenThread.join();
//	free(con->device);
	free(context);
	context = nullptr;
	return 0;
}

int register_command_callback(command_forwarder forward_command, const void *context) {
	if(context == nullptr) {
		return -1;
	}
	auto con = (struct context *)context;
	con->forwardCommand = forward_command;
	std::thread keyboardListener(listenKeyboard, con);
	con->listenThread.swap(keyboardListener);
//	con->listenThread.detach();
	return 0;
}

int forward_status(const struct buffer device_status, const struct device_identification device, const void *context) {
	CarAccessoryModule::ButtonStatus status;
	status.ParseFromArray(device_status.data, device_status.size);
	printf("[Car Accessory Module][INFO]: Received status from: %s/%s. Is pressed: %s\n", device.device_role,
		   device.device_name, status.ispressed() ? "true" : "false");
	return 0;
}

int
forward_error_message(const struct buffer error_msg, const struct device_identification device, const void *context) {
	CarAccessoryModule::ButtonError buttonError;
	buttonError.ParseFromArray(error_msg.data, error_msg.size);
	printf("[Car Accessory Module][INFO]: Received error message from: %s/%s. Press count: %d\n",
		   device.device_role, device.device_name, buttonError.presscount());
	return 0;
}

