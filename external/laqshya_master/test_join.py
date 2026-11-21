"""Smallest checks for the matcher rules. Run: python -I test_join.py"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))   # -I drops the script dir

from join import core, kind, kinds_ok, norm, state_key

assert norm("SDH Kadiri", lq=True) == "sub district hospital kadiri"
assert core(norm("Govt. General Hospital Kozhikode")) == "kozhikode"
assert kind(norm("DWH Amravati", lq=True)) == "mch"
assert kinds_ok("dh", "sdh") and not kinds_ok("chc", "dh") and not kinds_ok("mc", "mch")
assert kinds_ok("mc", math.nan) and kinds_ok(None, "dh")   # pandas gives NaN for a missing kind
assert state_key("DNH, D&D") == state_key("THE DADRA AND NAGAR HAVELI AND DAMAN AND DIU")
print("ok")
