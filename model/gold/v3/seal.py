"""Commitment scheme for the sealed gold v3 TEST labels (issue #51).

The TEST labels stay OFF the repo, with the custodian, until the lead posts "[type: update] model frozen" with a model
hash on #11. Only their SHA-256 is committed beforehand, so anyone can later check that the published labels are the
ones fixed before the model was.

    python model/gold/v3/seal.py commit  [--labels PATH]   # writes model/gold/v3/test_labels.sha256
    python model/gold/v3/seal.py verify  [--labels PATH]   # checks a labels file against the committed hash

The hash is over the file's exact bytes, so publish the same file, unmodified. Default location (outside the repo):
~/.cache/referral-saathi-gold-v3/test_labels.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
HASH = HERE / "test_labels.sha256"
DEFAULT = Path.home() / ".cache" / "referral-saathi-gold-v3" / "test_labels.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_labels(path: Path) -> None:
    """The labels must cover exactly the committed TEST sample, so the hash commits to a complete set."""
    labels = json.loads(path.read_text())["results"]
    want = {p["pair_id"] for p in json.loads((HERE / "test_sample.json").read_text())}
    got = {r["pair_id"] for r in labels}
    if got - want or want - got:
        raise SystemExit(f"labels do not match test_sample.json: missing {sorted(want - got)[:5]}, "
                         f"extra {sorted(got - want)[:5]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["commit", "verify"])
    ap.add_argument("--labels", type=Path, default=DEFAULT)
    a = ap.parse_args()
    path = a.labels.expanduser().resolve()
    if a.action == "commit" and ROOT in path.parents:
        raise SystemExit("keep the TEST labels outside the repo until the model is frozen")
    check_labels(path)
    h = digest(path)
    if a.action == "commit":
        HASH.write_text(f"{h}  test_labels.json\n")
        print(f"sealed: {h}")
        return 0
    want = HASH.read_text().split()[0]
    print("match" if h == want else f"MISMATCH: file {h}, committed {want}")
    return 0 if h == want else 1


if __name__ == "__main__":
    sys.exit(main())
