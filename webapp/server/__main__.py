"""Allow `python -m webapp.server` to launch."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from webapp.server import main

main()
