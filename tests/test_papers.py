from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from paperfeed import rank, sources
from paperfeed.__main__ import load, read_store, update

FIX = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).parent.parent
NOW = datetime(2026, 10, 28, 14, 0, tzinfo=timezone.utc)


class R:
    def __init__(self, path: str):
        self.content = (FIX / path).read_bytes()

    def json(self):
        return json.loads(self.content)


def fake_get(url: str) -> R:
    if "huggingface.co/api" in url:
        return R("hf_daily.json")
    if "arxiv.org/api" in url:
        return R("arxiv.xml")
    return R("blog.xml")


class NoLLM:
    available = False


class FakeLLM:
    available = True

    def __init__(self):
        self.prompts = []

    def complete_json(self, system, user):
        items = json.loads(user)["items"]
        self.prompts.append(items)
        return {"results": [{"idx": i["idx"], "relevance": 0.9 if "Memory" in i["title"] else 0.5,
                             "topic": "Agents & orchestration", "tldr": f"TLDR {i['title'][:20]}",
                             "why": "Useful for your agents."} for i in items]}, "groq:test"


def cfg(tmp_path) -> dict:
    c = load(str(ROOT / "papers.yaml"))
    c["sources"] = [{"type": "hf_daily", "name": "HF Daily Papers"},
                    {"type": "arxiv", "name": "arXiv", "queries": ["cat:cs.CL"]},
                    {"type": "rss", "feeds": {"Google Research": "https://g/rss"}}]
    c["settings"].update(store=str(tmp_path / "papers.json"), output=str(tmp_path / "index.html"))
    return c


def test_fetch_merges_sources_and_drops_old_items():
    c = load(str(ROOT / "papers.yaml"))
    items, report = sources.fetch_all(
        [{"type": "hf_daily"}, {"type": "arxiv", "name": "arXiv", "queries": ["q"]}], fake_get, 4, NOW)
    by = {p.id: p for p in items}
    assert "arxiv:2501.00001" not in by                       # older than lookback
    mem = by["arxiv:2610.34073"]                              # same paper from HF and arXiv
    assert mem.sources == ["HF Daily Papers", "arXiv"] and mem.upvotes == 31
    assert mem.code == "https://github.com/hexuan21/MemoryTax"
    assert by["arxiv:2610.37651"].title == "GEPA-Curator: Curated Learning for Self Improving Agents"
    assert report == {"hf_daily": 2, "arXiv": 3}
    assert c["topics"]


def test_prefilter_uses_topics_and_title_exclusions():
    c = load(str(ROOT / "papers.yaml"))
    items, _ = sources.fetch_all([{"type": "hf_daily"}, {"type": "arxiv", "queries": ["q"]},
                                  {"type": "rss", "feeds": {"Google Research": "u"}}], fake_get, 4, NOW)
    topics = rank.Topics(c["topics"])
    kept = rank.prefilter(items, topics, c["exclude_title"], 25, 60)
    titles = [p.title for p in kept]
    assert titles[0].startswith("Memory Tax")                    # many hits + popular
    assert not any("Robotic" in t for t in titles)               # excluded by title
    assert not any("Cohomology" in t or "Oracle" in t for t in titles)  # off-topic
    assert any("sleep framework" in t for t in titles)           # lab blog post kept
    assert kept[0].topic in topics.names


def test_update_scores_with_ai_and_renders_page(tmp_path):
    c, llm = cfg(tmp_path), FakeLLM()
    stats = update(c, llm, get=fake_get, now=NOW)
    assert stats["added"] == 3 and stats["ai_scored"] == 3
    store = read_store(tmp_path / "papers.json")
    mem = store["arxiv:2610.34073"]
    assert mem.relevance == 0.9 and mem.tldr.startswith("TLDR") and mem.scored_by == "groq:test"
    out = (tmp_path / "index.html").read_text()
    assert out.index("Memory Tax") < out.index("GEPA-Curator")   # most relevant first
    assert out.count("MUST READ") == 1 and "github.com/hexuan21/MemoryTax" in out and "90% match" in out
    assert "Discussion" in out and "PDF" in out

    # Second run: nothing new, nothing re-sent to the AI, page still has everything.
    llm2 = FakeLLM()
    stats = update(c, llm2, get=fake_get, now=NOW.replace(day=29))
    assert stats["added"] == 0 and llm2.prompts == [] and stats["on_page"] == 3


def test_falls_back_to_keywords_without_ai(tmp_path):
    c = cfg(tmp_path)
    update(c, NoLLM(), get=fake_get, now=NOW)
    mem = read_store(tmp_path / "papers.json")["arxiv:2610.34073"]
    assert mem.scored_by == "keywords" and 0.3 < mem.relevance <= 0.85
    assert mem.tldr == "Dedicated memory systems often underperform naive RAG."


def test_retention_drops_old_papers(tmp_path):
    c = cfg(tmp_path)
    update(c, NoLLM(), get=fake_get, now=NOW)
    c["sources"] = []
    stats = update(c, NoLLM(), get=fake_get, now=NOW.replace(month=12, day=30))
    assert stats["on_page"] == 0
