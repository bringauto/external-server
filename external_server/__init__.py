__all__ = (
    "argparse_init",
    "ExternalServer",
)

from .utils import argparse_init
from .external_server import ExternalServer

import os as _os

DIR = _os.path.dirname(_os.path.abspath(__file__))