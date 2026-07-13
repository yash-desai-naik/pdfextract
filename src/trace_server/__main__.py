"""Allow `python -m src.trace_server` to launch the FastAPI app."""

import os
import sys

# Ensure project root is on path (for `python -m src.trace_server` from any cwd)
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from src.trace_server import main

main()
