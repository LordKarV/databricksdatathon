"""Self-check for the name normalisers and matchers. Run: python -I test_join_test.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from join_test import city_agrees, norm, norm_state, norm_ulb  # noqa: E402


def test() -> None:
    assert norm("North & Middle Andaman ") == "north and middle andaman"
    assert norm_state("Orissa") == "odisha" and norm_state("Maharastra") == "maharashtra"
    assert norm_state("NCT of Delhi") == "delhi"
    assert norm_ulb("Municipal Corporation Of Greater Mumbai") == "greater mumbai"
    assert city_agrees("Gurgaon", ["gurgaon", "gurugram"])[0]
    assert not city_agrees("Raebareli", ["ghaziabad", "nasarpur"])[0]
    assert city_agrees(None, ["x"]) == (False, "", 0.0)
    print("ok")


if __name__ == "__main__":
    test()
