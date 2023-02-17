#include <thread>

extern "C" {
#include "external_server_interface.h"
}

struct context {
	char button;
	char* device;
	command_forwarder forwardCommand = nullptr;
};

void* init(key_getter get_key) {
	char* button = reinterpret_cast<char*>(get_key("button"));
	std::thread listenKeyboard {
		while(1) {

		}
	};
	struct context* context;
	context->button = button[0];
	return context;
}

