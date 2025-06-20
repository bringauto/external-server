import os
from external_server.__main__ import main
from external_server.server.single_car import CarServer
from external_server.server.all_cars import ExternalServer


PATH = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
