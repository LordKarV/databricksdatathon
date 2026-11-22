"""Run every validation check and write out/scorecard.json and out/scorecard.md.

Discovers validation/*/checks.py (one area per folder) plus validation/contracts_v2.py, runs every
check_* function each module defines, in source order, and exits 1 if any check has status fail.

Usage (from anywhere):
  .venv-viz/bin/python validation/run_all.py [--area NAME ...] [--skip-network] [--timeout S] [--jobs N]

Each area runs in its own worker process (areas import sibling modules named common, samples, ...,
which would clash in one interpreter). The parent enforces the per-check timeout: a check that runs
too long is recorded as not_run, its worker is killed, and a fresh worker resumes at the next check.

--skip-network blocks the network inside the workers instead of guessing which checks use it:
subprocess calls to sql.sh, gh, curl, wget and databricks return exit code 1 at once, outbound socket
connects raise OSError, and time.sleep is a no-op once a block has happened (retry back-off). The checks'
own error handling then reports the network part as not run. A check that crashed because of the block
is recorded as not_run; one that still produced a result keeps its status, with a note that its network
part was skipped.

Status rules: pass, warn, fail, not_run. A check that returns metric "not run" is recorded as not_run
whatever status it chose (some areas return warn for that), with the original kept in reported_status.
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = HERE / "out"
STATUSES = ("pass", "warn", "fail", "not_run")
BLOCKED_CMDS = {"sql.sh", "gh", "curl", "wget", "databricks"}
MAX_EXAMPLES = 5
MAX_TEXT = 600


# ------------------------------------------------------------------------------------------------ worker side
def _install_network_block(state: dict) -> None:
    """Make network calls fail fast inside this worker; state['tripped'] records that one was attempted."""
    import socket
    real_run, real_sleep = subprocess.run, time.sleep

    def blocked_run(args, *a, **kw):
        argv = [args] if isinstance(args, (str, bytes)) else list(args)
        if argv and Path(str(argv[0]).split()[0]).name in BLOCKED_CMDS:
            state["tripped"] = True
            return subprocess.CompletedProcess(argv, 1, "" if kw.get("text") or kw.get("universal_newlines") else b"",
                                               "blocked by run_all.py --skip-network")
        return real_run(args, *a, **kw)

    real_connect = socket.socket.connect

    def blocked_connect(self, address):
        if self.family == getattr(socket, "AF_UNIX", None):
            return real_connect(self, address)
        state["tripped"] = True
        raise OSError("network blocked by run_all.py --skip-network")

    def sleep(s):
        if not state["tripped"]:  # only retry back-off after a blocked call is skipped
            real_sleep(s)

    subprocess.run = blocked_run
    socket.socket.connect = blocked_connect
    socket.socket.connect_ex = lambda self, address: (blocked_connect(self, address), 0)[1]
    time.sleep = sleep


def _checks_in(mod) -> list:
    fns = [f for n, f in vars(mod).items() if n.startswith("check_") and callable(f)
           and getattr(f, "__module__", None) == mod.__name__]
    return sorted(fns, key=lambda f: f.__code__.co_firstlineno)  # source order: later checks may read earlier outputs


def worker(path: Path, start: int, skip_network: bool) -> None:
    """Run the checks of one module from index `start`; write one JSON line per event on the original stdout."""
    proto = os.fdopen(os.dup(1), "w", buffering=1)
    os.dup2(2, 1)  # check prints (Python and C level) go to stderr, which the parent logs
    sys.stdout = sys.stderr
    state = {"tripped": False}
    if skip_network:
        _install_network_block(state)
    os.chdir(ROOT)
    sys.path.insert(0, str(path.parent))
    import importlib.util
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception as e:  # an import error fails the whole area, reported once
        proto.write(json.dumps({"event": "import_error", "error": f"{type(e).__name__}: {e}",
                                "trace": traceback.format_exc().splitlines()[-6:]}) + "\n")
        return
    fns = _checks_in(mod)
    proto.write(json.dumps({"event": "list", "names": [f.__name__ for f in fns]}) + "\n")
    for i, fn in enumerate(fns[start:], start):
        state["tripped"] = False
        proto.write(json.dumps({"event": "start", "i": i, "name": fn.__name__}) + "\n")
        t0 = time.time()
        try:
            r = fn()
            err = None
        except Exception as e:  # a crashing check is reported as a failure, never dropped
            r, err = None, {"error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc().splitlines()[-4:]}
        proto.write(json.dumps({"event": "result", "i": i, "name": fn.__name__, "result": r, "crash": err,
                                "blocked": state["tripped"], "seconds": round(time.time() - t0, 1)},
                               default=str) + "\n")


# ------------------------------------------------------------------------------------------------ parent side
def _short(x, n=MAX_TEXT) -> str:
    s = x if isinstance(x, str) else json.dumps(x, default=str)
    return s if len(s) <= n else s[: n - 3] + "..."


def normalise(area: str, name: str, ev: dict) -> dict:
    """One scorecard row from a worker result event."""
    r, crash, blocked = ev.get("result"), ev.get("crash"), ev.get("blocked")
    row = {"area": area, "check": name[6:] if name.startswith("check_") else name, "seconds": ev.get("seconds")}
    if crash or not isinstance(r, dict):
        detail = crash["error"] if crash else f"check returned {type(r).__name__}, not a dict"
        if blocked:
            return {**row, "status": "not_run", "metric": "not run", "threshold": None,
                    "detail": f"network blocked (--skip-network); the check raised {detail}", "examples": []}
        return {**row, "status": "fail", "metric": "error", "threshold": None, "detail": detail,
                "examples": (crash or {}).get("trace", [])}
    status = str(r.get("status", "")).lower().replace("-", "_").replace(" ", "_")
    metric = r.get("metric")
    row.update(metric=_short(metric, 300), threshold=_short(r.get("threshold"), 200),
               detail=_short(r.get("detail", "")),
               examples=[_short(x, 300) for x in list(r.get("examples") or [])[:MAX_EXAMPLES]])
    not_run_text = isinstance(metric, str) and metric.strip().lower().startswith("not run")
    if status not in STATUSES:
        row.update(status="fail", detail=f"unknown status {r.get('status')!r}; {row['detail']}")
    elif not_run_text:
        row["status"] = "not_run"
    else:
        row["status"] = status
    if row["status"] != status and status in STATUSES:
        row["reported_status"] = status
    if blocked and row["status"] != "not_run":
        row["detail"] = "network part skipped (--skip-network). " + row["detail"]
    return row


def run_area(area: str, path: Path, timeout: float, skip_network: bool, logdir: Path) -> list[dict]:
    rows, start, names = [], 0, None
    log = open(logdir / f"{area}.log", "w")
    while True:
        cmd = [sys.executable, "-B", str(Path(__file__).resolve()), "--worker", str(path), "--start", str(start)]
        if skip_network:
            cmd.append("--skip-network")
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=log, text=True, start_new_session=True)
        q: queue.Queue = queue.Queue()
        threading.Thread(target=lambda: [q.put(ln) for ln in p.stdout] + [q.put(None)], daemon=True).start()
        current, deadline, resume = None, None, None
        while True:
            try:
                line = q.get(timeout=5)
            except queue.Empty:
                if current is not None and time.time() > deadline:
                    os.killpg(p.pid, signal.SIGKILL)
                    rows.append({"area": area, "check": current[1][6:], "status": "not_run", "metric": "timeout",
                                 "threshold": None, "detail": f"timed out after {timeout:.0f} s; worker killed",
                                 "examples": [], "seconds": timeout})
                    resume = current[0] + 1
                    break
                continue
            if line is None:  # worker exited
                if current is not None:  # died inside a check
                    rows.append({"area": area, "check": current[1][6:], "status": "fail", "metric": "worker died",
                                 "threshold": None, "detail": f"exit code {p.wait()}; see out/logs/{area}.log",
                                 "examples": [], "seconds": round(time.time() - deadline + timeout, 1)})
                    resume = current[0] + 1
                break
            ev = json.loads(line)
            if ev["event"] == "import_error":
                rows.append({"area": area, "check": "(import)", "status": "fail", "metric": "import error",
                             "threshold": None, "detail": ev["error"], "examples": ev["trace"], "seconds": 0})
            elif ev["event"] == "list":
                names = ev["names"]
            elif ev["event"] == "start":
                current, deadline = (ev["i"], ev["name"]), time.time() + timeout
                print(f"  [{area}] {ev['name']} ...", flush=True)
            elif ev["event"] == "result":
                row = normalise(area, ev["name"], ev)
                rows.append(row)
                print(f"  [{area}] {row['status']:7} {row['check']}: {row['metric']} ({row['seconds']} s)", flush=True)
                current = None
        p.wait()
        if resume is None or names is None or resume >= len(names):
            break
        start = resume
    log.close()
    return rows


def discover(areas: list[str] | None) -> list[tuple[str, Path]]:
    found = [(p.parent.name, p) for p in sorted(HERE.glob("*/checks.py"))]
    found.append(("contracts_v2", HERE / "contracts_v2.py"))
    if areas:
        unknown = set(areas) - {a for a, _ in found}
        if unknown:
            sys.exit(f"unknown area(s) {sorted(unknown)}; known: {[a for a, _ in found]}")
        found = [(a, p) for a, p in found if a in areas]
    return found


def write_scorecard(rows: list[dict], args, started: float) -> None:
    OUT.mkdir(exist_ok=True)
    counts = {s: sum(r["status"] == s for r in rows) for s in STATUSES}
    meta = {"generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "skip_network": args.skip_network,
            "timeout_s": args.timeout, "areas": sorted({r["area"] for r in rows}), "counts": counts,
            "seconds": round(time.time() - started, 1)}
    (OUT / "scorecard.json").write_text(json.dumps({"meta": meta, "checks": rows}, indent=1, default=str))

    def cell(x) -> str:
        return str(x if x is not None else "").replace("|", "/").replace("\n", " ")

    md = ["# Validation scorecard", "",
          f"Generated {meta['generated_utc']}, skip_network={args.skip_network}, timeout {args.timeout:.0f} s per "
          f"check, {meta['seconds']:.0f} s in all.", "",
          f"Totals: {counts['pass']} pass, {counts['warn']} warn, {counts['fail']} fail, {counts['not_run']} not run "
          f"(of {len(rows)}).", "", "## By area", "", "| area | pass | warn | fail | not run |", "|---|---|---|---|---|"]
    for a in meta["areas"]:
        ar = [r for r in rows if r["area"] == a]
        md.append(f"| {a} | " + " | ".join(str(sum(r['status'] == s for r in ar)) for s in STATUSES) + " |")
    md += ["", "## Checks", "", "| area | check | status | metric | detail |", "|---|---|---|---|---|"]
    order = {"fail": 0, "warn": 1, "not_run": 2, "pass": 3}
    for r in sorted(rows, key=lambda r: (r["area"], order[r["status"]])):
        md.append(f"| {r['area']} | {r['check']} | {r['status']} | {cell(r['metric'])} | {cell(_short(r['detail'], 240))} |")
    (OUT / "scorecard.md").write_text("\n".join(md) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--area", action="append", help="area folder name (repeatable or comma separated)")
    ap.add_argument("--skip-network", action="store_true", help="block warehouse, gh and web calls")
    ap.add_argument("--timeout", type=float, default=1200, help="seconds per check (default 1200)")
    ap.add_argument("--jobs", type=int, default=2, help="areas run at once (default 2)")
    ap.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    ap.add_argument("--start", type=int, default=0, help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.worker:
        worker(args.worker, args.start, args.skip_network)
        return 0
    areas = [a for x in args.area for a in x.split(",")] if args.area else None
    todo = discover(areas)
    logdir = OUT / "logs"
    logdir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as ex:
        results = list(ex.map(lambda ap_: run_area(*ap_, args.timeout, args.skip_network, logdir), todo))
    rows = [r for rs in results for r in rs]
    write_scorecard(rows, args, started)
    n_fail = sum(r["status"] == "fail" for r in rows)
    print(f"wrote {OUT / 'scorecard.json'} and scorecard.md: "
          + ", ".join(f"{sum(r['status'] == s for r in rows)} {s}" for s in STATUSES))
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
