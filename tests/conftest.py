import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# The dashboard modules (inti, koneksi) are imported the same way Streamlit imports them: from dasbor/.
for p in (ROOT, ROOT / "dasbor"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
