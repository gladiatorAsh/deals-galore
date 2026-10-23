"""Add items to the watchlist in config.yaml without disturbing its comments.

Used by the "Add to watchlist" workflow: the dashboard's Watch button opens a
pre-filled GitHub issue; when the repo owner submits it, the workflow calls
`python -m dealsgalore watch-add` with the issue body.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

import yaml

_PRICE_TAIL = re.compile(r"\s*(?:[-–—|]\s*)?\$\s?\d[\d,]*(?:\.\d+)?.*$")
_NOISE = re.compile(r"\[[^\]]*\]|\([^)]*\)")
STOP = {
    "the", "and", "with", "for", "pack", "piece", "pc", "set", "new", "free", "shipping",
    "deal", "sale", "off", "via", "at", "w", "in", "of", "a", "an", "to", "or", "by",
}
MAX_ITEMS = 50


def clean_title(title: str, limit: int = 70) -> str:
    t = _PRICE_TAIL.sub("", title)
    t = _NOISE.sub("", t)
    t = re.sub(r"\s+", " ", t).strip(" -–—|,")
    return (t[: limit - 1] + "…") if len(t) > limit else t


def suggest_match(title: str, n: int = 3) -> list[str]:
    words = re.findall(r"[a-z0-9][a-z0-9.\-]*", clean_title(title, 200).lower())
    out: list[str] = []
    for w in words:
        w = w.strip(".-")
        if len(w) < 2 or w in STOP or w in out or re.fullmatch(r"\d+(\.\d+)?", w):
            continue
        out.append(w)
        if len(out) == n:
            break
    return out


def issue_body(title: str, price: float | None) -> str:
    entry = {"item": clean_title(title), "max_price": price, "match": suggest_match(title)}
    block = yaml.safe_dump(entry, sort_keys=False, allow_unicode=True, width=200).strip()
    return (
        "Edit the values below if you like, then press **Submit new issue**.\n"
        "- `max_price`: alert when it's at or below this price\n"
        "- `match`: words that must ALL appear in a deal title\n\n"
        f"```yaml\n{block}\n```\n"
    )


def new_issue_url(repo: str, title: str, price: float | None) -> str:
    return (
        f"https://github.com/{repo}/issues/new"
        f"?title={quote('Watch: ' + clean_title(title, 60))}"
        f"&body={quote(issue_body(title, price))}"
    )


def parse_issue_body(body: str) -> dict[str, Any]:
    m = re.search(r"```(?:ya?ml)?\s*\n(.*?)```", body or "", re.DOTALL)
    data = yaml.safe_load(m.group(1) if m else body or "")
    if not isinstance(data, dict):
        raise ValueError("couldn't find a YAML block with item / max_price / match")
    item = str(data.get("item") or "").strip()
    if not item or len(item) > 120:
        raise ValueError("`item` is required (max 120 characters)")
    price = data.get("max_price")
    if price is not None:
        price = float(price)
        if not 0 < price < 1_000_000:
            raise ValueError("`max_price` must be a positive number")
    match = data.get("match") or suggest_match(item)
    if isinstance(match, str):
        match = [match]
    match = [str(w).strip().lower() for w in match if str(w).strip()][:8]
    if any(len(w) > 40 for w in match):
        raise ValueError("`match` words must be short")
    return {"item": item, "max_price": price, "match": match}


def _yaml_scalar(value: Any) -> str:
    return yaml.safe_dump(value, default_flow_style=True, width=1000).strip().removesuffix("...").strip()


def add_to_config(path: str | Path, entry: dict[str, Any]) -> str:
    """Insert entry at the end of the `watchlist:` section. Returns a status message."""
    path = Path(path)
    text = path.read_text()
    current = (yaml.safe_load(text) or {}).get("watchlist") or []
    names = {str(w.get("item", "")).lower() for w in current}
    if entry["item"].lower() in names:
        return f"'{entry['item']}' is already on the watchlist"
    if len(current) >= MAX_ITEMS:
        raise ValueError(f"watchlist is full ({MAX_ITEMS} items)")

    lines = text.splitlines()
    start = next(
        (i for i, l in enumerate(lines) if re.match(r"^watchlist:\s*(\[\])?\s*(#.*)?$", l)), None
    )
    if start is None:
        raise ValueError("config.yaml has no `watchlist:` section")
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i] and not lines[i][0].isspace()
         and not lines[i].startswith("#")),
        len(lines),
    )
    while end > start + 1 and not lines[end - 1].strip():
        end -= 1  # insert before the blank line(s) that separate sections

    block = [f"  - item: {_yaml_scalar(entry['item'])}"]
    if entry.get("match"):
        block.append(f"    match: {_yaml_scalar(entry['match'])}")
    if entry.get("max_price") is not None:
        block.append(f"    max_price: {entry['max_price']:g}")
    if re.match(r"^watchlist:\s*\[\]\s*$", lines[start]):
        lines[start] = "watchlist:"
    new_text = "\n".join(lines[:end] + block + lines[end:]) + "\n"

    # Never write a config that no longer parses or lost the item.
    parsed = (yaml.safe_load(new_text) or {}).get("watchlist") or []
    if not any(str(w.get("item")) == entry["item"] for w in parsed):
        raise ValueError("internal error: item not found after insert")
    path.write_text(new_text)
    return f"Added '{entry['item']}' (max ${entry['max_price']}, match {entry['match']})"
