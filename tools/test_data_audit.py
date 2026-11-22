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


def test_id_prefix_counts():
    uid = real("unique_id", "facility_location.parquet")[0]
    assert d.facility_hits(f"see {uid[:8]} for the example")["id_prefixes"] == 1
    assert not d.facility_hits("commit 0123abcd was reverted").get("id_prefixes")  # not a record prefix


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
    assert any("API keys" in x for x in d.findings("key=AIza" + "A" * 35))
    assert any("certificate" in x for x in d.findings("NABH H-2024-0001"))


def test_rescan_uses_the_same_detectors(tmp_path):
    (tmp_path / "a.md").write_text("route 85.1234567,25.6123456 for the demo")  # coordinates
    (tmp_path / "b.py").write_text("x = 1\n")
    assert d.check_copy(tmp_path) == 1
    (tmp_path / "a.md").unlink()
    assert d.check_copy(tmp_path) == 0


def test_name_head_before_bracket_counts():
    full = next(n for n in real("name", "facility_location.parquet") if " (" in n and len(d.words(n.split(" (")[0])) >= 2
                and any(len(x) >= 4 and x not in d.GENERIC for x in d.words(n.split(" (")[0])))
    assert d.facility_hits(f"we called {full.split(' (')[0]} yesterday")["names"] == 1
