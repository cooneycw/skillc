import subprocess, sys
from pathlib import Path
raise SystemExit(subprocess.call([sys.executable, '-I', str(Path(__file__).with_name('child.py'))]))
