"""The reading page (data/papers.html), published at ashutoshysingh.com/papers/ by the main site."""
from __future__ import annotations

import html
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .models import Paper

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Paper Desk</title>
<meta name="description" content="Daily AI/ML papers on RAG, agents, evaluation and LLM systems, ranked and summarized.">
<style>
:root{{--bg:#f7f7f4;--card:#fff;--ink:#17181a;--muted:#686c72;--line:#e3e4df;--accent:#2457c5;--must:#a8571a;--chip:#eef0ec}}
@media (prefers-color-scheme:dark){{:root{{--bg:#121315;--card:#1b1c1f;--ink:#e8e9ea;--muted:#9a9ea5;--line:#2c2e32;--accent:#7ea6ff;--must:#f0a463;--chip:#24262a}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 system-ui,-apple-system,Segoe UI,sans-serif}}
main{{max-width:820px;margin:0 auto;padding:28px 16px 64px}}
h1{{font-size:28px;margin:0 0 2px;letter-spacing:-.02em}}.sub{{color:var(--muted);margin:0 0 18px;font-size:14px}}
.bar{{display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin-bottom:10px}}
.chip{{border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:999px;padding:5px 12px;cursor:pointer;font:inherit;font-size:13px}}
.chip.on{{background:var(--ink);color:var(--bg);border-color:var(--ink)}}
.chip .n{{color:var(--muted);margin-left:4px;font-size:12px}}.chip.on .n{{color:inherit;opacity:.7}}
.tools{{display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin:8px 0 18px;font-size:13px;color:var(--muted)}}
.tools input[type=search]{{flex:1;min-width:180px;font:inherit;padding:7px 11px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--ink)}}
.tools label{{display:inline-flex;gap:5px;align-items:center;cursor:pointer;user-select:none}}
.p{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin-bottom:10px}}
.p.must{{border-color:var(--must)}}.p.done{{opacity:.55}}
.head{{display:flex;gap:8px;flex-wrap:wrap;align-items:center;font-size:12px;color:var(--muted);margin-bottom:3px}}
.topic{{color:var(--accent);font-weight:600;text-transform:uppercase;letter-spacing:.05em;font-size:11px}}
.badge{{border-radius:4px;padding:0 6px;font-size:11px;font-weight:700;letter-spacing:.03em}}
.b-must{{background:var(--must);color:#fff}}.b-new{{background:var(--chip);color:var(--ink)}}.b-blog{{background:var(--chip);color:var(--muted)}}
.rel{{margin-left:auto;font-variant-numeric:tabular-nums}}
.p h2{{font-size:16px;line-height:1.35;margin:2px 0 4px}}.p h2 a{{color:var(--ink);text-decoration:none}}.p h2 a:hover{{color:var(--accent)}}
.by{{font-size:13px;color:var(--muted);margin-bottom:6px}}
.tldr{{margin:0 0 4px}}.why{{margin:0;font-size:14px;color:var(--muted)}}.why b{{color:var(--ink);font-weight:600}}
details{{margin-top:6px;font-size:13px;color:var(--muted)}}summary{{cursor:pointer}}
.links{{display:flex;gap:6px;flex-wrap:wrap;margin-top:10px}}
.links a,.links button{{font:inherit;font-size:12px;font-weight:600;border:1px solid var(--line);background:none;color:var(--muted);border-radius:999px;padding:3px 10px;text-decoration:none;cursor:pointer}}
.links a:hover,.links button:hover{{color:var(--accent);border-color:var(--accent)}}
.links button.on{{color:var(--must);border-color:var(--must)}}
.empty{{color:var(--muted);padding:40px 0;text-align:center}}
.hint{{color:var(--muted);font-size:13px;margin-top:24px}}
</style></head><body><main>
<h1>Paper Desk</h1>
<p class="sub">AI/ML papers and lab posts picked for production RAG, agents and LLM systems · {total} items · updated {updated}</p>
<div class="bar" id="views">
<button class="chip" data-v="new">New<span class="n" id="n-new"></span></button>
<button class="chip" data-v="week">This week<span class="n" id="n-week"></span></button>
<button class="chip" data-v="all">Last {retention} days</button>
<button class="chip" data-v="saved">Saved<span class="n" id="n-saved"></span></button>
</div>
<div class="bar" id="topics"><button class="chip" data-t="all">All topics</button>{topic_chips}</div>
<div class="tools"><input type="search" id="q" placeholder="Search titles and summaries">
<label><input type="checkbox" id="hideread" checked>Hide read</label>
<label><input type="checkbox" id="showall">Show low-relevance</label></div>
<p class="empty" id="none" hidden>Nothing here yet. New papers arrive every morning.</p>
<div id="list">{items}</div>
<p class="hint">Ranked daily by AI for relevance to your work. <b>Must read</b> = the top {must} of the last 7 days. Saved and read marks stay in this browser.</p>
</main><script>
(function(){{
const KEY='paperdesk:v1';let st={{saved:{{}},done:{{}}}};
try{{const s=JSON.parse(localStorage.getItem(KEY)||'null');if(s&&s.saved&&s.done)st=s;}}catch(e){{}}
function save(){{try{{localStorage.setItem(KEY,JSON.stringify(st));}}catch(e){{}}}}
let view='week',topic='all';try{{view=localStorage.getItem(KEY+':view')||'week';}}catch(e){{}}
const now=Date.now(),H=3600e3,latest={latest};
const cards=[...document.querySelectorAll('.p')];
const q=document.getElementById('q'),hr=document.getElementById('hideread'),sa=document.getElementById('showall');
function inView(c,v){{const t=+c.dataset.ts;if(v==='new')return t>=latest-6*H;if(v==='week')return now-t<=7*24*H;
if(v==='saved')return !!st.saved[c.dataset.id];return true;}}
function render(){{let n=0;const s=q.value.trim().toLowerCase();
document.querySelectorAll('#views .chip').forEach(b=>b.classList.toggle('on',b.dataset.v===view));
document.querySelectorAll('#topics .chip').forEach(b=>b.classList.toggle('on',b.dataset.t===topic));
for(const c of cards){{const id=c.dataset.id,done=!!st.done[id];
c.classList.toggle('done',done);
c.querySelector('[data-a=save]').classList.toggle('on',!!st.saved[id]);
c.querySelector('[data-a=save]').textContent=st.saved[id]?'Saved':'Save';
c.querySelector('[data-a=done]').textContent=done?'Read ✓':'Mark read';
const ok=inView(c,view)&&(topic==='all'||c.dataset.t===topic)&&(view==='saved'||!(hr.checked&&done))
&&(sa.checked||view==='saved'||+c.dataset.rel>={min_rel})&&(!s||c.textContent.toLowerCase().includes(s));
c.hidden=!ok;n+=ok;}}
document.getElementById('none').hidden=n>0;
const cnt=v=>cards.filter(c=>inView(c,v)&&+c.dataset.rel>={min_rel}).length;
document.getElementById('n-new').textContent=cnt('new');document.getElementById('n-week').textContent=cnt('week');
document.getElementById('n-saved').textContent=Object.keys(st.saved).length||'';}}
document.querySelectorAll('#views .chip').forEach(b=>b.onclick=()=>{{view=b.dataset.v;try{{localStorage.setItem(KEY+':view',view);}}catch(e){{}}render();}});
document.querySelectorAll('#topics .chip').forEach(b=>b.onclick=()=>{{topic=b.dataset.t;render();}});
document.getElementById('list').onclick=e=>{{const b=e.target.closest('button[data-a]');if(!b)return;
const id=b.closest('.p').dataset.id,m=st[b.dataset.a==='save'?'saved':'done'];if(m[id])delete m[id];else m[id]=1;save();render();}};
[q,hr,sa].forEach(el=>el.oninput=render);render();
}})();
</script></body></html>
"""


def _e(s: object) -> str:
    return html.escape(str(s or ""), quote=True)


def _ts(p: Paper) -> datetime:
    for v in (p.first_seen, p.published):
        if v:
            return datetime.fromisoformat(v)
    return datetime.now(timezone.utc)


def _card(p: Paper, must: bool, is_new: bool, tz) -> str:
    authors = ", ".join(p.authors[:3]) + (" et al." if len(p.authors) > 3 else "")
    by = " · ".join(x for x in [authors, p.org if p.org and p.org not in authors else "",
                                 (datetime.fromisoformat(p.published).astimezone(tz).strftime("%b %-d")
                                  if p.published else ""),
                                 f"▲ {p.upvotes}" if p.upvotes else ""] if x)
    links = [f'<a href="{_e(p.url)}" target="_blank" rel="noopener">{"Read post" if p.kind == "blog" else "arXiv"}</a>']
    if p.pdf:
        links.append(f'<a href="{_e(p.pdf)}" target="_blank" rel="noopener">PDF</a>')
    if p.hf_url:
        links.append(f'<a href="{_e(p.hf_url)}" target="_blank" rel="noopener">Discussion</a>')
    if p.code:
        links.append(f'<a href="{_e(p.code)}" target="_blank" rel="noopener">Code</a>')
    badges = ""
    if must:
        badges += '<span class="badge b-must">MUST READ</span>'
    if is_new:
        badges += '<span class="badge b-new">NEW</span>'
    if p.kind == "blog":
        badges += f'<span class="badge b-blog">{_e(p.source).upper()}</span>'
    abstract = (f"<details><summary>Abstract</summary><p>{_e(p.abstract)}</p></details>"
                if p.abstract and p.kind == "paper" else "")
    return (
        f'<article class="p{" must" if must else ""}" data-id="{_e(p.id)}" data-t="{_e(p.topic or "Other")}" '
        f'data-rel="{p.relevance:.2f}" data-ts="{int(_ts(p).timestamp() * 1000)}">'
        f'<div class="head"><span class="topic">{_e(p.topic or "Other")}</span>{badges}'
        f'<span class="rel" title="Relevance to your work">{round(p.relevance * 100)}% match</span></div>'
        f'<h2><a href="{_e(p.url)}" target="_blank" rel="noopener">{_e(p.title)}</a></h2>'
        f'<div class="by">{_e(by)}</div>'
        f'<p class="tldr">{_e(p.tldr)}</p>'
        + (f'<p class="why"><b>For you:</b> {_e(p.why)}</p>' if p.why else "")
        + abstract
        + f'<div class="links">{"".join(links)}<button data-a="save">Save</button>'
        f'<button data-a="done">Mark read</button></div></article>'
    )


def render(papers: list[Paper], output: str | Path, topic_names: list[str], *,
           min_relevance: float = 0.45, must_reads: int = 5, retention_days: int = 60,
           timezone_name: str = "America/Los_Angeles", latest_run: datetime | None = None,
           now: datetime | None = None) -> Path:
    tz = ZoneInfo(timezone_name)
    now = now or datetime.now(timezone.utc)
    latest_run = latest_run or now
    # Must-reads: the best of the last 7 days, and only real matches.
    week = [p for p in papers if now - _ts(p) <= timedelta(days=7) and p.relevance >= max(min_relevance, 0.7)]
    must = {p.id for p in sorted(week, key=lambda p: p.relevance, reverse=True)[:must_reads]}
    ordered = sorted(papers, key=lambda p: (p.relevance, _ts(p)), reverse=True)
    new_cut = latest_run - timedelta(hours=6)
    items = "".join(_card(p, p.id in must, _ts(p) >= new_cut, tz) for p in ordered)
    present = [t for t in topic_names if any(p.topic == t for p in papers)]
    if any(not p.topic or p.topic not in topic_names for p in papers):
        present.append("Other")
    chips = "".join(f'<button class="chip" data-t="{_e(t)}">{_e(t)}</button>' for t in present)
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(PAGE.format(
        total=sum(1 for p in papers if p.relevance >= min_relevance),
        updated=now.astimezone(tz).strftime("%a %b %-d, %-I:%M %p %Z"),
        retention=retention_days, topic_chips=chips, items=items, must=must_reads,
        min_rel=f"{min_relevance:.2f}", latest=int(latest_run.timestamp() * 1000),
    ))
    return out
