"""Score out/map_*.jsonl: service accuracy per model and language, red-flag agreement,
verbatim decisive phrase, latency, errors. Writes out/scores.md and prints it."""
import json
import statistics
from collections import defaultdict
from pathlib import Path

OUT = Path(__file__).parent / "out"


def ok_service(row: dict) -> bool:
    exp = row["expected_service"]
    exp = exp if isinstance(exp, list) else [exp]
    return row["answer"].get("service") in exp


def pct(n: int, d: int) -> str:
    return f"{n}/{d}" if d else "-"


def score(path: Path) -> list[str]:
    rows = [json.loads(l) for l in path.read_text().splitlines()]
    model = path.stem.removeprefix("map_")
    lines = [f"### {model}", "", "| set | lang | service correct | red flag agrees (scored cases) | phrase verbatim |",
             "| --- | --- | --- | --- | --- |"]
    groups = defaultdict(list)
    for r in rows:
        groups[("hard" if r["id"].startswith("X") else "main", r["lang"])].append(r)
    for key in sorted(groups, key=lambda k: (k[0] != "main", k[1])):
        g = groups[key]
        rf = [r for r in g if r["expected_red_flag"] is not None and "service" in r["answer"]]
        lines.append(f"| {key[0]} | {key[1]} | {pct(sum(ok_service(r) for r in g), len(g))} | "
                     f"{pct(sum(r['answer']['red_flag'] == r['expected_red_flag'] for r in rf), len(rf))} | "
                     f"{pct(sum(r['answer'].get('decisive_phrase', '') in r['text'] for r in g), len(g))} |")
    for s in ("main", "hard"):
        g = [r for r in rows if (r["id"].startswith("X")) == (s == "hard")]
        rf = [r for r in g if r["expected_red_flag"] is not None and "service" in r["answer"]]
        lines.append(f"| {s} | all | {pct(sum(ok_service(r) for r in g), len(g))} | "
                     f"{pct(sum(r['answer']['red_flag'] == r['expected_red_flag'] for r in rf), len(rf))} | "
                     f"{pct(sum(r['answer'].get('decisive_phrase', '') in r['text'] for r in g), len(g))} |")
    ms = sorted(r["ms"] for r in rows)
    errs = [r for r in rows if "service" not in r["answer"]]
    lines += ["", f"Calls: {len(rows)}. Errors (call or schema): {len(errs)}. "
              f"Latency ms (wall, incl. CLI start): median {statistics.median(ms):.0f}, "
              f"p90 {ms[int(0.9 * (len(ms) - 1))]}, max {ms[-1]}.", ""]
    misses = [r for r in rows if "service" in r["answer"] and not ok_service(r)]
    rf_miss = [r for r in rows if "service" in r["answer"] and r["expected_red_flag"] is not None
               and r["answer"]["red_flag"] != r["expected_red_flag"]]
    not_verbatim = [r for r in rows if "service" in r["answer"] and r["answer"]["decisive_phrase"] not in r["text"]]
    for title, lst in (("Service misses", misses), ("Red-flag disagreements", rf_miss),
                       ("Decisive phrase not verbatim", not_verbatim)):
        lines.append(f"{title}:" + ("" if lst else " none"))
        lines += [f"- {r['id']} `{r['text']}` expected {r['expected_service']} / rf {r['expected_red_flag']}; "
                  f"got {r['answer']['service']} / {r['answer']['urgency']} / rf {r['answer']['red_flag']} / "
                  f"phrase `{r['answer']['decisive_phrase']}`" for r in lst]
    return lines + [""]


if __name__ == "__main__":
    text = "\n".join(l for p in sorted(OUT.glob("map_*.jsonl")) for l in score(p))
    (OUT / "scores.md").write_text(text)
    print(text)
