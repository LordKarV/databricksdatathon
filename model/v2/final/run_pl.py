"""EBM location head (fit_ebm/fit_pl.py reused unchanged) refit on the new facility labels; writes out/PL/."""
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "fit_ebm"))
import features as F  # noqa: E402
import fit_pl  # noqa: E402

F.LABEL_DIR = str(HERE / "out" / "labels_cc")
fit_pl.OUT = HERE / "out" / "PL"
fit_pl.main()
