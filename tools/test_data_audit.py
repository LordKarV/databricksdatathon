"""Detectors of the public-copy check (#83 review). Needs derived/v1; run: .venv-app/bin/python -m pytest tools -q"""
from __future__ import annotations

import sys
from pathlib import Path

import pyarrow.parquet as pq
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import data_audit as d  # noqa: E402, RUF100

pytestmark = pytest.mark.skipif(not (d.V1 / "claims.parquet").exists(), reason="needs derived/v1")


def real(col: str, file: str = "record_trust.parquet") -> list:
    return [v for v in pq.read_table(d.V1 / file, columns=[col]).column(0).to_pylist() if v]


def test_record_ids_count_only_when_many():
    uids = real("unique_id", "facility_location.parquet")[: d.PREFIXES_MANY]
    assert not d.facility_hits(f"see {uids[0][:8]} and {uids[1]} for the examples").get("record_ids")  # citations
    many = " ".join(u[:8] if i % 2 else u for i, u in enumerate(uids))  # prefixes and full ids alike
    assert d.facility_hits(many)["record_ids"] == d.PREFIXES_MANY
    assert not d.facility_hits(" ".join(f"{i:08x}" for i in range(20))).get("record_ids")  # not record prefixes


def test_own_domain_and_email_count():
    dom = min(d.dictionary()["domains"])
    assert d.facility_hits(f"website www.{dom}")["domains"] == 1
    email = min(d.dictionary()["emails"])
    assert d.facility_hits(f"write to {email}")["emails"] == 1


def test_public_hosts_never_count():
    assert not d.facility_hits("see icmr.gov.in, aiims.edu, en.wikipedia.org and tinyurl.com").get("domains")


def test_single_name_word_counts_and_allowlist_clears():
    tok = min(d.dictionary()["tokens"])
    assert d.facility_hits(f"refer to {tok.title()} today")["name_words"] == 1
    assert not d.facility_hits("the code beats the samay lexicon").get("name_words")


def test_short_claims_need_several_per_file():
    short = d.dictionary()["short"]
    texts = []
    for t in real("text", "claims.parquet"):
        w = d.words(t)
        if d.SHORT_CLAIM[0] <= len(w) <= d.SHORT_CLAIM[1] and hash(tuple(w)) in short:
            texts.append(t)
        if len(texts) == d.SHORT_CLAIMS_PER_FILE:
            break
    assert not d.facility_hits(texts[0]).get("short_claims")  # one could be coincidence
    assert d.facility_hits("\n".join(texts))["short_claims"] >= d.SHORT_CLAIMS_PER_FILE


def test_devanagari_words_are_words():
    assert d.words("Please refer जल्दी") == ["please", "refer", "जल्दी"]


def test_secrets_and_certificates_in_findings():
    assert any("api keys" in x for x in d.findings("key=AIza" + "A" * 35))
    assert d.detect("NABH H-2024-0001, PESHCO-2023-12345.pdf, HOS/2019/C1234 and tcf:7")["list_entries"] == 4
    assert not d.detect("ISO-9001-2015 and CVE-2024-12345").get("list_entries")


def test_rescan_uses_the_same_detectors(tmp_path):
    (tmp_path / "a.md").write_text("route 85.1234567,25.6123456 for the demo")  # coordinates
    (tmp_path / "b.py").write_text("x = 1\n")
    assert d.check_copy(tmp_path) == 1
    (tmp_path / "a.md").unlink()
    assert d.check_copy(tmp_path) == 0


def test_name_head_before_bracket_counts():
    def head_ok(n: str) -> bool:
        w = d.words(n.split(" (")[0])
        return len(w) >= 2 and any(len(x) >= 4 and x not in d.GENERIC for x in w)
    full = next(n for n in real("name", "facility_location.parquet") if " (" in n and head_ok(n))
    assert d.facility_hits(f"we called {full.split(' (')[0]} yesterday")["names"] == 1


def test_repo_rules():
    assert d.repo_rules("x.md", d.Counter(api_keys=1)) == ["secret"]
    many = d.Counter(list_entries=d.LIST_MANY)
    assert d.repo_rules("viz/x.csv", many) == ["restricted_copy"]
    assert d.repo_rules("derived/v2/facility_attributes.parquet", many) == ["mentions"]  # cited per-facility facts
    assert d.repo_rules("a.csv", d.Counter(phones=d.BULK_FACILITIES)) == ["bulk_rows"]
    assert d.repo_rules("a.csv", d.Counter(claim_spans=d.CLAIMS_MANY - 5, short_claims=5)) == ["claim_copy"]
    assert d.repo_rules("a.md", d.Counter(names=2)) == ["mentions"]
    assert d.repo_rules("a.md", d.Counter(uuids=3)) == []  # any UUID is not a record id


def test_notebook_outputs_are_read():
    nb = {"cells": [{"cell_type": "code", "source": ["x = 1"],
                     "outputs": [{"text": ["printed"]}, {"data": {"text/html": ["<td>shown</td>"]}}]}]}
    raw = d.json.dumps(nb).encode()
    assert "printed" in d.text_from("a.ipynb", raw) and "shown" in d.text_from("a.ipynb", raw)
    assert "printed" not in d.text_from("a.ipynb", raw, outputs=False)


def test_git_blobs_reads_head():
    first = next(d.git_blobs("HEAD"))
    assert isinstance(first[0], str) and isinstance(first[1], bytes)
