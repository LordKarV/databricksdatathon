"""Run: .venv/bin/python -I -m pytest external/nmc_colleges/test_join.py (or python -I test_join.py)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from join import name_ok, norm, pin_int  # noqa: E402


def test_name_gate():
    n = lambda s: norm(s)
    assert name_ok(n("Katihar Medical College, Katihar"), n("Katihar Medical College and Hospital, Katihar"), 88)
    assert name_ok(n("AIIMS Bhopal"), n("All India Institute of Medical Sciences, Bhopal"), 88)
    # shared generic words alone must not match
    assert not name_ok(n("Tezpur Medical College & Hospital, Tezpur"), n("City Hospital"), 88)
    assert not name_ok(n("Government Medical College, Kota"), n("Government Medical College, Ananthapuram"), 88)


def test_pin_int():
    assert pin_int("Port Blair-744104 (A & N Islands)") == 744104
    assert pin_int("12345") is None


if __name__ == "__main__":
    test_name_gate()
    test_pin_int()
    print("ok")
