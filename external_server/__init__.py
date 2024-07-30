__all__ = (
    "parsed_script_args",
    "ExternalServer",
)

import os
from .server import ExternalServer


PATH = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))