"""Whole-system diagnostics for Product Analysis Studio.

Checks the layers a test suite does not: the real database file, the real
migration state, the DAG the pipeline will actually execute, and the provider
credentials. Prints one line per check and exits non-zero if any FAILed.
"""

from __future__ import annotations

import importlib
import pkgutil
import sqlite3
import sys
import traceback
from pathlib import Path

# Run from anywhere: `python scripts/diagnose.py` must work without the caller
# having to set PYTHONPATH.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

RESULTS: list[tuple[str, str, str]] = []


def check(name: str):
    def wrap(fn):
        try:
            status, detail = fn()
        except Exception as exc:  # noqa: BLE001 - a failing check must not stop the run
            status, detail = "FAIL", f"{type(exc).__name__}: {exc}"
            traceback.print_exc(file=sys.stderr)
        RESULTS.append((name, status, detail))
        return fn

    return wrap


# --- 1. Every module imports -------------------------------------------------
@check("imports")
def _imports():
    import pas

    broken = []
    count = 0
    for mod in pkgutil.walk_packages(pas.__path__, "pas."):
        count += 1
        try:
            importlib.import_module(mod.name)
        except Exception as exc:  # noqa: BLE001
            broken.append(f"{mod.name}: {exc}")
    if broken:
        return "FAIL", "; ".join(broken[:3])
    return "PASS", f"{count} modules"


# --- 2. Database integrity ---------------------------------------------------
@check("db integrity")
def _db():
    from pas.config import load_config

    cfg = load_config()
    conn = sqlite3.connect(cfg.db_path)
    conn.row_factory = sqlite3.Row
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        return "FAIL", integrity
    fk = conn.execute("PRAGMA foreign_key_check").fetchall()
    if fk:
        return "FAIL", f"{len(fk)} foreign-key violations"
    tables = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
    ).fetchone()[0]
    return "PASS", f"integrity ok, 0 fk violations, {tables} tables"


# --- 3. Migrations all applied, no duplicate index names ---------------------
@check("migrations")
def _migrations():
    from pas.config import load_config
    from pas.storage.db import MIGRATIONS_DIR

    cfg = load_config()
    conn = sqlite3.connect(cfg.db_path)
    conn.row_factory = sqlite3.Row
    applied = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
    on_disk = {int(f.stem.split("_", 1)[0]) for f in MIGRATIONS_DIR.glob("*.sql")}
    missing = on_disk - applied
    if missing:
        return "FAIL", f"unapplied: {sorted(missing)}"
    names = [
        r[0]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
    ]
    dupes = {n for n in names if names.count(n) > 1}
    if dupes:
        return "FAIL", f"duplicate index names: {dupes}"
    return "PASS", f"{len(applied)} applied, {len(names)} indexes, no duplicates"


# --- 4. The agent DAG resolves ----------------------------------------------
@check("agent DAG")
def _dag():
    from pas.agents.pipeline import FULL_PIPELINE, execution_levels, pipeline_for

    levels = execution_levels(FULL_PIPELINE)
    scheduled = [a for lvl in levels for a in lvl]
    if len(scheduled) != len(FULL_PIPELINE):
        return "FAIL", "a cycle dropped agents from the schedule"
    produced: set[str] = set()
    for level in levels:
        for agent in level:
            unmet = set(agent.requires) - produced
            if unmet:
                return "FAIL", f"{agent.name} scheduled before {sorted(unmet)}"
        produced.update(a.name for a in level)
    # The only depth that narrows the pipeline is "intelligence"; every other
    # value falls through to the full run. Assert they actually differ, so a
    # regression that collapsed them would show up here.
    quick, full = len(pipeline_for("intelligence")), len(pipeline_for("full"))
    if quick >= full:
        return "FAIL", f"intelligence depth ({quick}) does not narrow the full run ({full})"
    return "PASS", (
        f"{len(FULL_PIPELINE)} agents in {len(levels)} levels, deps ordered; "
        f"intelligence={quick} full={full}"
    )


# --- 5. Provider credentials -------------------------------------------------
@check("provider config")
def _provider():
    from pas.config import load_config

    cfg = load_config()
    if not cfg.is_configured:
        return "WARN", "no API key set - analysis will not run"
    return "PASS", f"fast={cfg.fast_model} deep={cfg.deep_model}"


# --- 6. Service-level diagnostics -------------------------------------------
@check("service diagnostics")
def _service():
    from pas.service import StudioService

    svc = StudioService()
    d = svc.diagnostics()
    bad = []
    if d["failed_agent_runs"]:
        bad.append(f"{d['failed_agent_runs']} failed agent runs")
    if d["failed_sources"]:
        bad.append(f"{d['failed_sources']} failed/blocked sources")
    usage = d["usage"]
    # The key is `cost`. Reading a name that does not exist returns None and
    # formats as $0.0000, which reads as "no spend" rather than as a bad key.
    if "cost" not in usage:
        return "FAIL", f"usage_summary keys changed: {sorted(usage)}"
    detail = (
        f"spend ${float(usage['cost']):.4f} over {usage['calls']} calls, "
        f"{usage['tokens']:,} tokens, {d['active_jobs']} active jobs"
    )
    if bad:
        return "WARN", detail + " - " + "; ".join(bad)
    return "PASS", detail


# --- 7. SSRF guard still blocks the things it must --------------------------
@check("SSRF guard")
def _ssrf():
    from pas.research.safety import UnsafeURLError, validate_url

    def allowed(url: str) -> bool:
        try:
            # DNS off: these are checked as literals/schemes, and a resolver
            # round trip per URL would make the check depend on the network.
            validate_url(url, resolve_dns=False)
            return True
        except (UnsafeURLError, ValueError):
            return False

    blocked = [
        "http://localhost/admin",
        "http://127.0.0.1:8501/",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5/internal",
        "http://192.168.1.1/",
        "file:///etc/passwd",
        "gopher://evil.test/",
    ]
    leaked = [u for u in blocked if allowed(u)]
    if leaked:
        return "FAIL", f"allowed: {leaked}"
    if not allowed("https://example.com/pricing"):
        return "FAIL", "blocks ordinary public URLs"
    return "PASS", f"{len(blocked)} hostile URLs blocked, public URL allowed"


def main() -> int:
    for name, status, detail in RESULTS:
        print(f"{status:<5} {name:<22} {detail}")
    failed = [r for r in RESULTS if r[1] == "FAIL"]
    warned = [r for r in RESULTS if r[1] == "WARN"]
    print(
        f"\n{len(RESULTS)} checks: "
        f"{len(RESULTS) - len(failed) - len(warned)} pass, "
        f"{len(warned)} warn, {len(failed)} fail"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
