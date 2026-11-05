import sys
from pathlib import Path

# Ensure tkinder is in sys.path
tkinder_dir = Path(__file__).resolve().parent.parent
if str(tkinder_dir) not in sys.path:
    sys.path.insert(0, str(tkinder_dir))
