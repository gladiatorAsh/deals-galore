# deals-galore

A free, config-driven deal and gift finder. Every two hours it reads Slickdeals,
Reddit deal subreddits, and any RSS feed or Best Buy SKU you list. It matches
posts against your **watchlist** (things you want, at a target price) and your
private **gift profiles** (family members' interests and budgets), and uses a
free LLM to separate real finds from noise. Great matches are pushed to your
phone right away; good ones arrive in a daily digest.

Everything runs on free tiers: GitHub Actions, GitHub Models (with Gemini as a
fallback), GitHub Pages, and Telegram/ntfy/Gmail.

```
GitHub Actions (every 2h)
  → fetch Slickdeals / Reddit / RSS / Best Buy
  → dedupe against data/deals.json, drop stale or excluded posts
  → keyword + budget prefilter (no LLM cost for the 95% that can't match)
  → LLM scores matches in batches (GitHub Models → Gemini → heuristic)
  → price-history check: down-rank "deals" above the 90-day median
  → instant alert (score ≥ 0.8) · daily digest (score ≥ 0.5) · dashboard
  → commit data/deals.json + docs/index.html
```

## Setup (about 10 minutes)

### 1. Edit `config.yaml`
Add watchlist items with a `max_price`, and add or remove sources. The file is
commented throughout.

### 2. Add your gift profiles as a secret
This repo is public, so family details never go in a committed file.
Copy the format from `gifts.example.yaml`. Then, in GitHub:
**Settings → Secrets and variables → Actions → New repository secret**, name it
`GIFT_PROFILES`, and paste the YAML.

### 3. Notifications with Telegram (default)

Alerts come from your own private Telegram bot. It's free, and only you can see
its chat.

1. **Create the bot.** In Telegram, search for **@BotFather** (blue check mark),
   send `/newbot`, and pick a display name and a username ending in `bot`, for
   example `ash_deals_bot`. BotFather replies with a token like
   `123456789:AAH...`. Keep it secret: anyone with it can control the bot.
2. **Start a chat with it.** Tap the `t.me/...` link BotFather gives you, press
   **Start**, and send any message, such as `hi`. A bot can't message you until
   you've messaged it.
3. **Find your chat ID.** In a browser, open
   `https://api.telegram.org/bot<TOKEN>/getUpdates`, using your token. Find
   `"chat":{"id":123456789,...` and copy that number. If the page shows
   `"result":[]`, send the bot another message and refresh.
4. **Add two repository secrets:** `TELEGRAM_BOT_TOKEN` (the token) and
   `TELEGRAM_CHAT_ID` (the number).

Instant alerts show the price, why it matched, and a tappable link to the deal.
The daily digest arrives as one grouped message, split if it's long.
For a shared family channel, add the bot to a Telegram group and use the
group's chat ID instead. Group IDs start with `-`.

Other channels, all optional and usable alongside Telegram:

| Channel | Secrets | How to get them |
|---|---|---|
| ntfy push | `NTFY_TOPIC` (optional `NTFY_SERVER`, `NTFY_TOKEN`) | Install the ntfy app, subscribe to a long random topic name, and use the same name as the secret. |
| Email digest | `SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_TO` | Gmail address plus a Google **app password** (needs 2-Step Verification). |

### 4. Optional extras
- `GEMINI_API_KEY`: a free key from Google AI Studio, used when GitHub Models' daily quota runs out.
- `BESTBUY_API_KEY`: a free key from developer.bestbuy.com, for `bestbuy` SKU sources.

GitHub Models needs no key: the workflow's built-in `GITHUB_TOKEN` has
`models: read`.

### 5. Turn it on
1. **Actions** tab → enable workflows if prompted.
2. Run **Check sources and notifications** manually. It prints how many items
   each source returned and sends a test alert.
3. Run **Scan for deals** once manually. After that it runs on its schedule.
4. Optional dashboard: **Settings → Pages → Deploy from a branch → `main` / `/docs`**.
   The dashboard never shows gift recipient names.

## Running locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp gifts.example.yaml gifts.local.yaml   # git-ignored; edit it
python -m dealsgalore sources            # items per source
python -m dealsgalore scan --dry-run     # prints alerts instead of sending
python -m dealsgalore digest --dry-run
pytest -q
```

Set `GITHUB_TOKEN` (a personal access token with the `models:read` permission)
or `GEMINI_API_KEY` locally to use LLM scoring. Without either, it falls back to
heuristic scoring.

## Adding sources

- **Any RSS/Atom feed:** add a `type: rss` entry with a `url`. Most deal blogs and
  forums have one.
- **New kind of source:** write `fetch(entry, ctx) -> list[Deal]` in
  `dealsgalore/sources/` and register it in `ADAPTERS` in `sources/__init__.py`.

## Free-tier budget

| Resource | Usage | Free limit |
|---|---|---|
| Actions minutes | ~12 runs/day × ~1 min | Unlimited on public repos |
| GitHub Models | ≤ 6 batched requests per run, usually 0–2 | Daily per-model quota (low-tier models ~150/day) |
| Gemini | Fallback only | Free tier, about 5–15 requests/min |

During Black Friday week you can change the cron in `scan.yml` to hourly.

## Privacy model

- `config.yaml`, `data/deals.json` and the dashboard are public. They contain deals,
  prices and your watchlist, nothing else.
- Gift profiles live only in the `GIFT_PROFILES` secret. Recipient names are never
  written to the store. LLM reasons are scrubbed of profile names, and the
  digest re-derives "gift for X" at send time.
- Profiles are sent to the LLM provider for scoring. Keep notes generic if that
  matters to you.

## Known limitations

- **Reddit** sometimes refuses requests from cloud IPs, including GitHub Actions
  runners. Failures are logged and skipped. If Reddit stays at 0 in the check
  workflow, rely on Slickdeals or run the scan from your own machine.
- Prices are parsed from post titles plus the LLM's reading of them. Always open
  the link before buying.
- GitHub disables scheduled workflows after 60 days without repository
  activity. The bot's own commits normally keep it active.
