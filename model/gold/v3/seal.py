"""Commitment scheme for the sealed gold v3 TEST labels (issue #51; rules decided on PR #76).

Order of events:
1. Custodian labels TEST off the repo, then `seal.py commit`: writes test_labels.sha256 (refuses to overwrite) with
   two hashes, and posts both as a comment on #51 (GitHub's timestamp binds them).
2. Lead commits model/v2/test_predictions.parquet (TEST pair ids, p, band, model_version) and its sha256, posted on
   #51: the model freeze.
3. Custodian publishes test_labels.json once: `seal.py open --model-hash <sha256 from step 2>` checks the labels
   against the sealed hashes and appends the opening to OPENING_LOG.md. A second opening is refused.
Anyone can then run `seal.py verify --labels model/gold/v3/test_labels.json`.

Two hashes over a canonical form, so a re-save (indentation, key order) is told apart from an edit:
  full      every row, sorted by pair_id, keys sorted, separators (",", ":"), UTF-8
  verdicts  "pair_id<TAB>service verdict" lines, sorted by pair_id
Default labels location (outside the repo): ~/.cache/referral-saathi-gold-v3/test_labels.json; keep a second copy
outside any cache directory, and one with the custodian's human.
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
HASH = HERE / "test_labels.sha256"
LOG = HERE / "OPENING_LOG.md"
DEFAULT = Path.home() / ".cache" / "referral-saathi-gold-v3" / "test_labels.json"


def rows(path: Path) -> list[dict]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    return sorted(doc["results"] if isinstance(doc, dict) else doc, key=lambda r: r["pair_id"])


def digests(labels: list[dict]) -> dict[str, str]:
    full = json.dumps(labels, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    verdicts = "".join(f"{r['pair_id']}\t{r['service']}\n" for r in labels).encode("utf-8")
    return {"full": hashlib.sha256(full).hexdigest(), "verdicts": hashlib.sha256(verdicts).hexdigest()}


def check_labels(labels: list[dict]) -> None:
    """The labels must cover exactly the committed TEST sample, so the hash commits to a complete set."""
    want = {p["pair_id"] for p in json.loads((HERE / "test_sample.json").read_text())}
    got = {r["pair_id"] for r in labels}
    if got - want or want - got:
        raise SystemExit(f"labels do not match test_sample.json: missing {sorted(want - got)[:5]}, "
                         f"extra {sorted(got - want)[:5]}")


def read_seal() -> dict[str, str]:
    """{"full": hex, "verdicts": hex} from test_labels.sha256 ("<hex>  <name>" lines)."""
    if not HASH.exists():
        raise SystemExit(f"no seal yet: {HASH.name} is missing (run `seal.py commit` first)")
    out = {}
    for line in HASH.read_text().splitlines():
        h, name = line.split()
        out[name.removeprefix("test_labels.").removesuffix(".canonical")] = h
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["commit", "verify", "open"])
    ap.add_argument("--labels", type=Path, default=DEFAULT)
    ap.add_argument("--model-hash", help="open: sha256 of model/v2/test_predictions.parquet, as posted on #51")
    a = ap.parse_args()
    path = a.labels.expanduser().resolve()
    labels = rows(path)
    check_labels(labels)
    h = digests(labels)
    if a.action == "commit":
        if ROOT in path.parents:
            raise SystemExit("keep the TEST labels outside the repo until the model is frozen")
        if HASH.exists():
            raise SystemExit(f"{HASH.name} exists: a seal is never overwritten (raise it on #51 instead)")
        HASH.write_text(f"{h['full']}  test_labels.full.canonical\n{h['verdicts']}  test_labels.verdicts.canonical\n")
        print(f"sealed\n  full      {h['full']}\n  verdicts  {h['verdicts']}\npost both on #51")
        return 0
    want = read_seal()
    ok = h["full"] == want.get("full") and h["verdicts"] == want.get("verdicts")
    if a.action == "verify":
        print("match" if ok else f"MISMATCH: file {h}, sealed {want}")
        return 0 if ok else 1
    # open
    if not ok:
        raise SystemExit(f"refusing to open: labels do not match the seal ({h} vs {want})")
    if not a.model_hash or len(a.model_hash) != 64:
        raise SystemExit("open needs --model-hash: the sha256 of model/v2/test_predictions.parquet posted on #51")
    if LOG.exists() and "| opened |" in LOG.read_text():
        raise SystemExit("TEST was already opened once (OPENING_LOG.md); a second opening is not allowed")
    head = "" if LOG.exists() else ("# Gold v3 TEST opening log\n\nOne opening only (PR #76).\n\n"
                                    "| event | when (UTC) | who | model predictions sha256 | labels sha256 (full) |\n"
                                    "| --- | --- | --- | --- | --- |\n")
    when = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
    with LOG.open("a") as fh:
        fh.write(head + f"| opened | {when} | {getpass.getuser()} | {a.model_hash} | {h['full']} |\n")
    print(f"opened; logged in {LOG.relative_to(ROOT)}. Copy the labels to model/gold/v3/test_labels.json and commit "
          "both files together.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
