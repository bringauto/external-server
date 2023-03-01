#include <iostream>
#include <csignal>

#include <external_server_interface.h>
#include <CarAccessoryModule.pb.h>



int getKey(const char* const key, buffer *value void *context) {
	value->data = malloc(sizeof(char));
	value->size = 1;
	return 0;
}

int forwardCommand(const struct buffer command, const struct device_identification device, void *context) {
	std::cout << "Serializing command to ExternalServer Command message" << std::endl;
	return 0;
}

int main() {
	int myContext = {get_module_number()};
	auto context = init(getKey, (void *)&myContext);
	register_command_callback(forwardCommand, context, (void *)&myContext);

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
		forward_status(statusData, device, context);
		sleep(5);
	}
	std::cout << "Destroying context" << std::endl;
	destroy(&context);
	std::cout << "Context successfully destroyed" << std::endl;
}