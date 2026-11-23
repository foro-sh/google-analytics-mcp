import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools import manifest  # noqa: E402

(ROOT / "foro-tools.json").write_text(json.dumps(manifest(), indent=2) + "\n")
