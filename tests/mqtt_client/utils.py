import os
import subprocess

import external_server as _external_server


class MQTTBrokerTest:

    def __init__(self, start: bool = False):
        self.broker_process = None
        if start:
            self.start()

    def start(self):
        assert self.broker_process is None
        root_dir = os.path.dirname(_external_server.DIR)
        mqtt_broker_script = os.path.join(root_dir, "lib/mqtt-testing/interoperability/startbroker.py")
        self.broker_process = subprocess.Popen(["python", mqtt_broker_script])
        assert isinstance(self.broker_process, subprocess.Popen)

    def stop(self):
        if self.broker_process:
            self.broker_process.terminate()
            self.broker_process.wait()