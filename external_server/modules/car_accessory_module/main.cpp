#include <iostream>
#include <csignal>

#include <external_server_interface.h>
#include <CarAccessoryModule.pb.h>
#include <thread>



void commandGetter(std::atomic<bool> *listenCommands, void *context) {
	int commandsLeft = 0;
	while(*listenCommands) {
		if(wait_for_command(3000, context) == 0) {
			do {
				buffer command;
				struct device_identification device;
				commandsLeft = get_command(&command, &device, context);
				auto cmd = CarAccessoryModule::ButtonCommand();
				cmd.ParseFromArray(command.data, command.size);
				std::cout << "Command from device " << device.device_name << " " << cmd.command() << std::endl;
			} while(commandsLeft > 0);
		} else {
			std::cout << "Waiting again" << std::endl;
		}
	}
}

int main() {
	struct config configuration;

	char key[] = "button";
	configuration.parameters = new struct key_value;
	configuration.size = 1;
	configuration.parameters->key.data = (void *)key;
	configuration.parameters->key.size = 6;
	char value[] = "b";
	configuration.parameters->value.data = (void *)value;
	configuration.parameters->value.size = 1;



	auto context = init(configuration);
//	register_command_callback(forwardCommand, context, (void *)&myContext);

	struct device_identification device = {0, "GreenButton", "A-1"};
	device_connected(device, context);

	std::atomic<bool> listenCommands = true;
	std::thread commandGet(commandGetter, &listenCommands, context);


	CarAccessoryModule::ButtonStatus status;
	status.set_ispressed(true);

	struct buffer statusData {};
	statusData.size = status.ByteSizeLong();
	statusData.data = malloc(statusData.size);
	if(statusData.data == nullptr) {
		printf("[Car Accessory Module][ERROR]: Memory allocation error\n");
	}
	status.SerializeToArray(statusData.data, statusData.size);
	for(int i = 0; i < 3; ++i) {
		forward_status(statusData, device, context);
		sleep(5);
	}
	std::cout << "Destroying context" << std::endl;
	destroy(&context);
	std::cout << "Context successfully destroyed" << std::endl;
	listenCommands = false;
	commandGet.join();
}