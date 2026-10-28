from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any


@dataclass
class Paper:
    id: str
    title: str
    url: str
    abstract: str = ""
    authors: list[str] = field(default_factory=list)
    org: str | None = None
    published: str | None = None
    source: str = ""
    sources: list[str] = field(default_factory=list)
    category: str | None = None
    kind: str = "paper"            # paper | blog
    pdf: str | None = None
    hf_url: str | None = None
    code: str | None = None
    project: str | None = None
    upvotes: int = 0
    summary_hint: str | None = None  # Hugging Face's one-line AI summary, when present
    # filled in by ranking
    topic: str | None = None
    topics: list[str] = field(default_factory=list)
    relevance: float = 0.0
    tldr: str = ""
    why: str = ""
    scored_by: str = ""
    first_seen: str | None = None

    def __post_init__(self) -> None:
        if self.source and self.source not in self.sources:
            self.sources = [*self.sources, self.source]

    def merge(self, other: "Paper") -> "Paper":
        """Combine the same paper seen in two sources (keep the richest fields)."""
        for f in fields(self):
            mine, theirs = getattr(self, f.name), getattr(other, f.name)
            if f.name == "sources":
                setattr(self, f.name, list(dict.fromkeys([*mine, *theirs])))
            elif f.name == "upvotes":
                setattr(self, f.name, max(mine, theirs))
            elif f.name == "abstract" and len(theirs or "") > len(mine or ""):
                setattr(self, f.name, theirs)
            elif not mine and theirs:
                setattr(self, f.name, theirs)
        return self

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Paper":
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})
