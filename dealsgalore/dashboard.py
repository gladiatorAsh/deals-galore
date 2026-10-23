"""Static dashboard written to docs/index.html and served by GitHub Pages.

The page is public, so it shows deals and watchlist matches only, never gift
recipient names (those exist only in the GIFT_PROFILES secret).
"""
from __future__ import annotations

import html
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .store import Store

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Deals Galore</title>
<style>
:root{{--bg:#faf8f5;--card:#fff;--ink:#1d1b18;--muted:#6f6a63;--line:#e8e3dc;--accent:#b4441c;--good:#2f7d4a}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151412;--card:#1e1c1a;--ink:#ece8e2;--muted:#a19a90;--line:#2f2c28;--accent:#f0875c;--good:#6fc28d}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}}
main{{max-width:860px;margin:0 auto;padding:28px 16px 60px}}
h1{{font-size:28px;margin:0 0 4px;letter-spacing:-.02em}}.sub{{color:var(--muted);margin:0 0 20px}}
.filters{{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px}}
.filters button{{border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:999px;padding:6px 12px;cursor:pointer;font:inherit;font-size:13px}}
.filters button.on{{background:var(--ink);color:var(--bg);border-color:var(--ink)}}
.deal{{display:grid;grid-template-columns:72px 1fr;gap:14px;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px;margin-bottom:10px}}
.price{{font-weight:700;font-size:17px;font-variant-numeric:tabular-nums}}.score{{font-size:12px;color:var(--good)}}
.deal a{{color:var(--ink);text-decoration:none;font-weight:600}}.deal a:hover{{color:var(--accent)}}
.meta{{color:var(--muted);font-size:13px;margin-top:4px}}.tag{{display:inline-block;font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--accent);margin-bottom:2px}}
.empty{{color:var(--muted);padding:40px 0;text-align:center}}
</style></head><body><main>
<h1>Deals Galore</h1>
<p class="sub">{count} deals scored ≥ {min_score} · updated {updated} UTC</p>
<div class="filters"><button class="on" data-f="all">All</button><button data-f="watch">Watchlist</button><button data-f="gift">Gift ideas</button></div>
<div id="list">{items}</div>
</main><script>
document.querySelectorAll('.filters button').forEach(b=>b.onclick=()=>{{
document.querySelectorAll('.filters button').forEach(x=>x.classList.toggle('on',x===b));
document.querySelectorAll('.deal').forEach(d=>d.hidden=b.dataset.f!=='all'&&d.dataset.kind!==b.dataset.f);}});
</script></body></html>
"""


def _item(rec: dict[str, Any]) -> str:
    price = f"${rec['price']:,.0f}" if rec.get("price") is not None else "—"
    kind = "watch" if rec.get("watch_item") else "gift"
    tag = f"Watchlist · {rec['watch_item']}" if rec.get("watch_item") else "Gift idea"
    meta = " · ".join(
        x for x in (rec.get("source"), rec.get("reason"), rec.get("price_note"), rec["first_seen"][:16].replace("T", " ")) if x
    )
    return (
        f'<div class="deal" data-kind="{kind}"><div><div class="price">{html.escape(price)}</div>'
        f'<div class="score">score {rec.get("score", 0):.2f}</div></div><div>'
        f'<div class="tag">{html.escape(tag)}</div>'
        f'<a href="{html.escape(rec["url"])}" target="_blank" rel="noopener">{html.escape(rec["title"])}</a>'
        f'<div class="meta">{html.escape(meta)}</div></div></div>'
    )


def render(store: Store, output: str | Path, min_score: float, max_items: int) -> Path:
    rows = store.recent(min_score)[:max_items]
    items = "".join(_item(rec) for _, rec in rows) or '<p class="empty">No deals yet.</p>'
    page = PAGE.format(
        count=len(rows),
        min_score=min_score,
        updated=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        items=items,
    )
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page)
    return out
