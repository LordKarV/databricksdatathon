"""Random sample of 60 source URLs with their assigned class, for manual review.
Manual labels (A about this facility, L list page, D other entity, U unknown) are stored in
handcheck_domains_labeled.csv; run with --eval to score url_kind() against them."""
import random
import sys

import pandas as pd

sys.path.insert(0, "/Users/karthikvattem/projects/datathon/audit/provenance")
from common import OUT, facilities, host, jlist  # noqa: E402
from domains import classify  # noqa: E402
from q1_sources import official_hosts, url_kind  # noqa: E402


def sample():
    f = facilities()
    pairs = [(r.unique_id, r["name"], u, official_hosts(r)) for _, r in f.iterrows()
             for u in jlist(r.source_urls)]
    random.seed(7)
    s = random.sample(pairs, 60)
    d = pd.DataFrame([(uid, n, u, classify(host(u), off, n)) for uid, n, u, off in s],
                     columns=["unique_id", "name", "url", "class"])
    d.to_csv(f"{OUT}/handcheck_domains_sample.csv", index=False)
    print(d.to_string())


def evaluate():
    lab = pd.read_csv(f"{OUT}/handcheck_domains_labeled.csv")
    lab["detector"] = [url_kind(u, n, c) for u, n, c in zip(lab.url, lab["name"], lab["class"])]
    print(pd.crosstab(lab.manual_label, lab.detector))
    print(lab[(lab.detector == "about") != (lab.manual_label == "A")][
        ["manual_label", "detector", "name", "url"]].to_string())


if __name__ == "__main__":
    evaluate() if "--eval" in sys.argv else sample()
