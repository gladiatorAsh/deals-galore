"""python -m paperfeed update | sources"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
import yaml

from dealsgalore.config import LLMProvider
from dealsgalore.llm import LLMClient

from . import page, rank, sources
from .models import Paper

log = logging.getLogger("paperfeed")


def load(path: str) -> dict[str, Any]:
    cfg = yaml.safe_load(Path(path).read_text()) or {}
    cfg.setdefault("settings", {})
    return cfg


def llm_client(main_config: str = "config.yaml") -> LLMClient:
    """Reuse the deal finder's free AI providers (same GROQ/GEMINI keys)."""
    try:
        data = yaml.safe_load(Path(main_config).read_text()) or {}
    except OSError:
        data = {}
    return LLMClient([LLMProvider(**p) for p in (data.get("llm") or {}).get("providers", [])])


def _getter():
    s = requests.Session()
    s.headers["User-Agent"] = "paper-desk/0.1 (+https://github.com/gladiatorAsh/deals-galore)"

    def get(url: str):
        r = s.get(url, timeout=30)
        r.raise_for_status()
        return r
    return get


def read_store(path: Path) -> dict[str, Paper]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text() or "{}")
    return {k: Paper.from_dict(v) for k, v in (raw.get("papers") or {}).items()}


def write_store(path: Path, papers: dict[str, Paper], last_run: datetime) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"last_run": last_run.isoformat(timespec="seconds"),
                                "papers": {k: p.to_dict() for k, p in papers.items()}},
                               indent=1, ensure_ascii=False) + "\n")


def update(cfg: dict[str, Any], llm: LLMClient, get=None, now: datetime | None = None) -> dict[str, Any]:
    st = cfg["settings"]
    now = now or datetime.now(timezone.utc)
    store_path = Path(st.get("store", "data/papers.json"))
    known = read_store(store_path)
    fetched, report = sources.fetch_all(cfg.get("sources") or [], get or _getter(),
                                        int(st.get("lookback_days", 4)), now)
    for p in fetched:  # refresh popularity of papers already on the page
        if p.id in known:
            known[p.id].upvotes = max(known[p.id].upvotes, p.upvotes)
            known[p.id].sources = list(dict.fromkeys([*known[p.id].sources, *p.sources]))
    topics = rank.Topics(cfg.get("topics") or [])
    new = [p for p in fetched if p.id not in known]
    picked = rank.prefilter(new, topics, cfg.get("exclude_title") or [],
                            int(st.get("popular_upvotes", 25)), int(st.get("max_candidates", 60)))
    by_ai = rank.score(picked, cfg.get("reader", ""), topics, llm, int(st.get("batch_size", 10)))
    stamp = now.isoformat(timespec="seconds")
    for p in picked:
        p.first_seen = stamp
        known[p.id] = p
    cutoff = now - timedelta(days=int(st.get("retention_days", 60)))
    known = {k: p for k, p in known.items()
             if datetime.fromisoformat(p.first_seen or stamp) >= cutoff}
    write_store(store_path, known, now)
    page.render(list(known.values()), st.get("output", "docs/papers/index.html"), topics.names,
                min_relevance=float(st.get("min_relevance", 0.45)), must_reads=int(st.get("must_reads", 5)),
                retention_days=int(st.get("retention_days", 60)),
                timezone_name=st.get("timezone", "America/Los_Angeles"), latest_run=now, now=now)
    return {"sources": report, "fetched": len(fetched), "new": len(new), "added": len(picked),
            "ai_scored": by_ai, "on_page": len(known)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="paperfeed")
    ap.add_argument("command", choices=["update", "sources"])
    ap.add_argument("--config", default=os.environ.get("PAPERS_CONFIG", "papers.yaml"))
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    cfg = load(args.config)
    if args.command == "sources":
        items, report = sources.fetch_all(cfg.get("sources") or [], _getter(),
                                          int(cfg["settings"].get("lookback_days", 4)))
        print(json.dumps(report, indent=1))
        return 0 if items else 1
    stats = update(cfg, llm_client())
    print(json.dumps(stats, indent=1))
    failed = [k for k, v in stats["sources"].items() if isinstance(v, str)]
    if failed and os.environ.get("GITHUB_ACTIONS"):
        print(f"::warning::Paper sources failed: {', '.join(failed)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
