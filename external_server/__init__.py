__all__ = (
    "argparse_init",
    "ExternalServer",
)

import os
from .utils import argparse_init
from .server import ExternalServer


PATH = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))