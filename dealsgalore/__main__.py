"""CLI:  python -m dealsgalore scan | digest | sources | test-notify  [--dry-run]"""
from __future__ import annotations

import argparse
import logging
import sys

from .config import load_config
from .notifiers import Alert, configured_notifiers, send_all
from .pipeline import digest, scan
from .store import Store


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="dealsgalore")
    ap.add_argument("command", choices=["scan", "digest", "sources", "test-notify"])
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--store", default="data/deals.json")
    ap.add_argument("--dry-run", action="store_true", help="print alerts instead of sending them")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    cfg = load_config(args.config)
    notifiers = configured_notifiers(dry_run=args.dry_run)

    if args.command == "sources":
        from .sources import FetchContext, fetch_all

        st = cfg.settings
        ctx = FetchContext(user_agent=st.user_agent, timeout=st.request_timeout, watchlist=cfg.watchlist)
        counts: dict[str, int] = {}
        for d in fetch_all(cfg.sources, ctx):
            counts[d.source] = counts.get(d.source, 0) + 1
        for src, n in sorted(counts.items()):
            print(f"{n:5d}  {src}")
        return 0 if counts else 1

    if args.command == "test-notify":
        a = Alert(title="deals-galore test notification", url="https://github.com/gladiatorAsh/deals-galore",
                  price=None, score=1.0, source="test", reason="If you can read this, alerts work.")
        ok = send_all(notifiers, "alert", a) + send_all(notifiers, "digest", [a], "deals-galore test digest")
        return 0 if ok else 1

    store = Store(args.store)
    if args.command == "scan":
        scored = scan(cfg, store, notifiers)
        hits = sum(1 for s in scored if s.score >= cfg.settings.instant_threshold)
        logging.getLogger("dealsgalore").info("Done: %d scored, %d instant alerts", len(scored), hits)
    else:
        digest(cfg, store, notifiers)
    return 0


if __name__ == "__main__":
    sys.exit(main())
