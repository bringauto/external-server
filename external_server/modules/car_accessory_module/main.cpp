#include <iostream>
#include <csignal>

#include <external_server_interface.h>
#include <CarAccessoryModule.pb.h>



void* getKey(const char* const key) {
	return (void *)"b";
}

int forwardCommand(const struct buffer command, const struct device_identification device) {
	std::cout << "Serializing command to ExternalServer Command message" << std::endl;
	return 0;
}

int main() {
	auto context = init(getKey);
	register_command_callback(forwardCommand, context);

	struct device_identification device = {0, "GreenButton", "A-1"};
	device_connected(device, context);

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

	} {
		forward_status(statusData, device, context);
		sleep(5);
	}
	std::cout << "Destroying context" << std::endl;
	destroy(&context);
	std::cout << "Context successfully destroyed" << std::endl;
}