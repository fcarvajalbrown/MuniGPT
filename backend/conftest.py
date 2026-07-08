"""
pytest bootstrap for the MuniGPT backend.

Ensures the backend/ directory is importable so tests can `import rag`,
`import ingest`, `import main` regardless of the directory pytest is invoked
from. Backend modules are flat (no package), matching how main.py imports them.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
