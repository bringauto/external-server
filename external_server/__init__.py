import os
from .server.single_car import CarServer
from .server.all_cars import ExternalServer


PATH = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
