"""Keyword prefilter, then AI relevance scoring with a plain-English summary."""
from __future__ import annotations

import json
import logging
import math
import re
from typing import Any

from dealsgalore.llm import LLMClient, LLMUnavailable

from .models import Paper

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You curate a daily AI/ML reading list for one engineer (see reader).
For EVERY item (papers and lab blog posts) return:
- relevance 0.0-1.0 for THIS reader's work. 0.8+ = they should read it this week
  (a technique, system or finding they could apply or must know about).
  0.5-0.75 = useful background. Below 0.4 = not for them (off-topic, narrow
  domain, pure theory, or a marketing/product/partnership post with no
  technical substance).
- topic: the single best-fitting name from topics, or null.
- tldr: plain English, max 40 words: what they did and the key result. No hype,
  no "this paper". Include a number if the abstract gives one.
- why: max 22 words: how it could matter for the reader's work, or why it
  does not. Concrete (e.g. "drop-in reranker that cuts RAG latency").
Judge from the title and abstract only; do not invent results.
Respond with JSON only:
{"results": [{"idx": 0, "relevance": 0.0, "topic": null, "tldr": "", "why": ""}]}"""


def _kw_regex(keyword: str) -> re.Pattern:
    return re.compile(r"(?<![a-z0-9])" + re.escape(keyword.lower()) + r"(?:s|es)?(?![a-z0-9])")


class Topics:
    def __init__(self, topics: list[dict[str, Any]]):
        self.names = [t["name"] for t in topics]
        self.rx = {t["name"]: [_kw_regex(k) for k in t.get("keywords") or []] for t in topics}

    def hits(self, paper: Paper) -> dict[str, int]:
        text = f"{paper.title} {paper.abstract}".lower()
        out = {}
        for name, patterns in self.rx.items():
            n = sum(1 for p in patterns if p.search(text))
            if n:
                out[name] = n
        return out


def prefilter(papers: list[Paper], topics: Topics, exclude_title: list[str],
              popular_upvotes: int, limit: int) -> list[Paper]:
    """Keep papers with topic keyword hits (or very popular ones), best first."""
    excl = [_kw_regex(x) for x in exclude_title]
    keep: list[tuple[float, Paper]] = []
    for p in papers:
        if any(r.search(p.title.lower()) for r in excl):
            continue
        hits = topics.hits(p)
        if not hits and p.upvotes < popular_upvotes:
            continue
        p.topics = sorted(hits, key=hits.get, reverse=True)
        p.topic = p.topics[0] if p.topics else None
        rank = sum(hits.values()) + math.log1p(p.upvotes) * 1.5 + (0.5 if p.kind == "blog" else 0)
        keep.append((rank, p))
    keep.sort(key=lambda x: x[0], reverse=True)
    return [p for _, p in keep[:limit]]


def heuristic(p: Paper) -> None:
    """Used when no AI key is set or the free quota is used up."""
    hits = len(p.topics)
    p.relevance = round(min(0.85, 0.3 + 0.12 * hits + 0.06 * math.log1p(p.upvotes)), 2)
    first = re.split(r"(?<=[.!?])\s", p.abstract, maxsplit=1)[0] if p.abstract else ""
    p.tldr = p.summary_hint or first[:300]
    p.why = ("Matches: " + ", ".join(p.topics[:3])) if p.topics else "Popular on Hugging Face today"
    p.scored_by = "keywords"


def build_prompt(batch: list[Paper], reader: str, topic_names: list[str]) -> str:
    items = [{"idx": i, "kind": p.kind, "title": p.title, "abstract": p.abstract[:1100],
              "org": p.org, "keyword_topics": p.topics[:3]} for i, p in enumerate(batch)]
    return json.dumps({"reader": reader, "topics": topic_names, "items": items}, indent=1)


def score(papers: list[Paper], reader: str, topics: Topics, llm: LLMClient,
          batch_size: int = 10) -> int:
    """Score in place. Returns how many the AI scored (the rest use keywords)."""
    scored = 0
    for start in range(0, len(papers), max(1, batch_size)):
        batch = papers[start:start + batch_size]
        data: dict[str, Any] = {}
        provider = ""
        if llm.available:
            try:
                data, provider = llm.complete_json(SYSTEM_PROMPT, build_prompt(batch, reader, topics.names))
            except LLMUnavailable as exc:
                log.warning("AI unavailable, using keyword ranking: %s", exc)
        got = set()
        for r in data.get("results", []) if isinstance(data, dict) else []:
            try:
                i = int(r.get("idx"))
                rel = max(0.0, min(1.0, float(r.get("relevance"))))
            except (TypeError, ValueError):
                continue
            if not 0 <= i < len(batch) or i in got:
                continue
            p = batch[i]
            p.relevance = round(rel, 2)
            if r.get("topic") in topics.names:
                p.topic = r["topic"]
            p.tldr = str(r.get("tldr") or p.summary_hint or "")[:400]
            p.why = str(r.get("why") or "")[:240]
            p.scored_by = provider
            got.add(i)
        scored += len(got)
        for i, p in enumerate(batch):
            if i not in got:
                heuristic(p)
    return scored
