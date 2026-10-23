"""Free notification channels. Each is enabled only when its env vars are set.

  Telegram : TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
  ntfy     : NTFY_TOPIC (pick something unguessable), optional NTFY_SERVER,
             NTFY_TOKEN (only for a self-hosted or reserved, protected topic)
  Email    : SMTP_USER, SMTP_PASSWORD (Gmail app password), EMAIL_TO,
             optional SMTP_HOST (default smtp.gmail.com), SMTP_PORT (465)
"""
from __future__ import annotations

import html
import logging
import os
import re
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

import requests

log = logging.getLogger(__name__)


@dataclass
class Alert:
    title: str
    url: str
    price: float | None
    score: float
    source: str
    reason: str = ""
    recipient: str | None = None
    watch_item: str | None = None
    price_note: str = ""
    store: str | None = None
    premium: str | None = None

    @property
    def tag(self) -> str:
        star = "★ Premium · " if self.premium else ""
        if self.watch_item:
            return f"{star}{self.watch_item}"
        if self.recipient:
            return f"Gift for {self.recipient}"
        return "Deal"

    def lines(self) -> list[str]:
        price = f"${self.price:,.2f}" if self.price is not None else "price ?"
        extra = " · ".join(x for x in (self.reason, self.price_note) if x)
        where = f" at {self.store}" if self.store else ""
        return [f"{self.tag} — {price}{where} ({self.score:.2f}, {self.source})", self.title, extra]


class Notifier:
    name = "base"

    def alert(self, a: Alert) -> None: ...

    def digest(self, alerts: list[Alert], subject: str) -> None: ...


class ConsoleNotifier(Notifier):
    name = "console"

    def alert(self, a: Alert) -> None:
        print("🔔 " + "\n   ".join(x for x in a.lines() if x) + f"\n   {a.url}")

    def digest(self, alerts: list[Alert], subject: str) -> None:
        print(f"=== {subject} ===")
        for a in alerts:
            self.alert(a)


class TelegramNotifier(Notifier):
    name = "telegram"

    def __init__(self, token: str, chat_id: str):
        self.url = f"https://api.telegram.org/bot{self.clean_token(token)}/sendMessage"
        self.chat_id = chat_id.strip().strip("'\"")

    @staticmethod
    def clean_token(token: str) -> str:
        """Forgive common paste mistakes: whitespace, quotes, a 'bot' prefix or a full URL."""
        t = token.strip().strip("'\"").strip()
        if "api.telegram.org/bot" in t:
            t = t.split("api.telegram.org/bot", 1)[1].split("/", 1)[0]
        if t.lower().startswith("bot") and ":" in t:
            t = t[3:]
        return t

    def _send(self, text: str) -> None:
        r = requests.post(
            self.url,
            json={
                "chat_id": self.chat_id,
                "text": text[:4000],
                "parse_mode": "HTML",
                "disable_web_page_preview": False,
            },
            timeout=20,
        )
        if r.status_code >= 400:
            # Telegram explains failures in the body, e.g. "chat not found" or
            # "Unauthorized"; never include the URL, which contains the token.
            try:
                detail = r.json().get("description", "")
            except ValueError:
                detail = r.text[:200]
            hint = {
                401: "check TELEGRAM_BOT_TOKEN",
                404: "TELEGRAM_BOT_TOKEN is malformed; it should look like 123456789:AA...",
                400: "check TELEGRAM_CHAT_ID and that you pressed Start in the bot chat",
                403: "the bot was blocked or removed from the chat",
            }.get(r.status_code, "")
            raise RuntimeError(f"Telegram HTTP {r.status_code}: {detail} {('(' + hint + ')') if hint else ''}".strip())

    @staticmethod
    def _fmt(a: Alert) -> str:
        head, title, extra = a.lines()
        out = f"<b>{html.escape(head)}</b>\n<a href=\"{html.escape(a.url)}\">{html.escape(title)}</a>"
        return out + (f"\n<i>{html.escape(extra)}</i>" if extra else "")

    def alert(self, a: Alert) -> None:
        self._send("🔔 " + self._fmt(a))

    def digest(self, alerts: list[Alert], subject: str) -> None:
        chunk = f"<b>{html.escape(subject)}</b>"
        for a in alerts:
            piece = "\n\n" + self._fmt(a)
            if len(chunk) + len(piece) > 3800:
                self._send(chunk)
                chunk = ""
            chunk += piece
        if chunk:
            self._send(chunk)


class NtfyNotifier(Notifier):
    """ntfy.sh push. Subscribe to the same topic in the ntfy phone app.

    Instant alerts are tappable (open the deal) and use high priority for the
    very best matches; the digest is split across messages to stay under
    ntfy's 4 KB message limit.
    """

    name = "ntfy"
    MAX_BYTES = 3800

    def __init__(self, topic: str, server: str = "https://ntfy.sh", token: str | None = None):
        self.endpoint = f"{server.rstrip('/')}/{topic}"
        self.token = token

    def _post(self, title: str, body: str, click: str | None = None,
              priority: str = "default", tags: str = "shopping_cart") -> None:
        headers = {"Title": title.encode("utf-8"), "Tags": tags, "Priority": priority}
        if click:
            headers["Click"] = click
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        requests.post(self.endpoint, data=body.encode("utf-8"), headers=headers, timeout=20).raise_for_status()

    @staticmethod
    def priority_for(a: Alert) -> str:
        return "high" if a.score >= 0.9 else "default"

    def alert(self, a: Alert) -> None:
        head, title, extra = a.lines()
        tags = "eyes" if a.watch_item else "gift" if a.recipient else "shopping_cart"
        self._post(head, f"{title}\n{extra}".strip(), a.url, self.priority_for(a), tags)

    def digest(self, alerts: list[Alert], subject: str) -> None:
        entries = [f"{a.lines()[0]}\n{a.title}\n{a.url}" for a in alerts]
        chunks: list[str] = []
        current = ""
        for e in entries:
            candidate = f"{current}\n\n{e}" if current else e
            if current and len(candidate.encode("utf-8")) > self.MAX_BYTES:
                chunks.append(current)
                current = e
            else:
                current = candidate
        if current:
            chunks.append(current)
        for i, chunk in enumerate(chunks, 1):
            title = subject if len(chunks) == 1 else f"{subject} ({i}/{len(chunks)})"
            self._post(title, chunk.encode("utf-8")[: self.MAX_BYTES].decode("utf-8", "ignore"),
                       tags="newspaper")


class EmailNotifier(Notifier):
    name = "email"

    def __init__(self, user: str, password: str, to: str, host: str, port: int):
        self.user, self.password, self.to, self.host, self.port = user, password, to, host, port

    def _send(self, subject: str, text: str, html_body: str) -> None:
        msg = EmailMessage()
        msg["Subject"], msg["From"], msg["To"] = subject, self.user, self.to
        msg.set_content(text)
        msg.add_alternative(html_body, subtype="html")
        with smtplib.SMTP_SSL(self.host, self.port, timeout=30) as s:
            s.login(self.user, self.password)
            s.send_message(msg)

    def alert(self, a: Alert) -> None:
        # Email is for the digest; instant alerts go to push channels.
        return None

    def digest(self, alerts: list[Alert], subject: str) -> None:
        text = "\n\n".join("\n".join(x for x in a.lines() if x) + f"\n{a.url}" for a in alerts)
        rows = "".join(
            f"<tr><td style='padding:8px 0;border-bottom:1px solid #eee'>"
            f"<div style='color:#555;font-size:12px'>{html.escape(a.lines()[0])}</div>"
            f"<a href='{html.escape(a.url)}'>{html.escape(a.title)}</a>"
            f"<div style='color:#777;font-size:12px'>{html.escape(a.lines()[2])}</div></td></tr>"
            for a in alerts
        )
        self._send(subject, text, f"<h2>{html.escape(subject)}</h2><table>{rows}</table>")


_TOKEN_RE = re.compile(r"\d{6,12}:[A-Za-z0-9_-]{30,40}")


def describe_token_problem(raw: str) -> str | None:
    """Explain what's off about a token's shape without revealing its contents."""
    t = TelegramNotifier.clean_token(raw)
    if _TOKEN_RE.fullmatch(t):
        return None
    if ":" not in t:
        return (f"{len(t)} characters and no ':'; a bot token is '<digits>:<~35 characters>' "
                "(did you paste the chat ID or bot username instead?)")
    head, tail = t.split(":", 1)
    parts = []
    if not head.isdigit():
        parts.append("the part before ':' should be only digits")
    if not 30 <= len(tail) <= 40:
        parts.append(f"the part after ':' is {len(tail)} characters (expected ~35)")
    if re.search(r"[^A-Za-z0-9_\-:]", t):
        parts.append("it contains spaces or unexpected characters such as < >")
    return "; ".join(parts) or "unexpected format"


def configured_notifiers(dry_run: bool = False) -> list[Notifier]:
    if dry_run:
        return [ConsoleNotifier()]
    env = os.environ
    out: list[Notifier] = []
    if env.get("TELEGRAM_BOT_TOKEN") and env.get("TELEGRAM_CHAT_ID"):
        problem = describe_token_problem(env["TELEGRAM_BOT_TOKEN"])
        if problem:
            log.warning("TELEGRAM_BOT_TOKEN doesn't look like a bot token: %s", problem)
        chat = env["TELEGRAM_CHAT_ID"].strip().strip("'\"")
        if not re.fullmatch(r"-?\d+", chat):
            log.warning("TELEGRAM_CHAT_ID should be a number like 123456789 (got %d chars, "
                        "not all digits)", len(chat))
        out.append(TelegramNotifier(env["TELEGRAM_BOT_TOKEN"], env["TELEGRAM_CHAT_ID"]))
    elif env.get("TELEGRAM_BOT_TOKEN") or env.get("TELEGRAM_CHAT_ID"):
        log.warning("Telegram needs BOTH TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID secrets")
    if env.get("NTFY_TOPIC"):
        out.append(NtfyNotifier(env["NTFY_TOPIC"], env.get("NTFY_SERVER") or "https://ntfy.sh",
                                env.get("NTFY_TOKEN") or None))
    if env.get("SMTP_USER") and env.get("SMTP_PASSWORD") and env.get("EMAIL_TO"):
        out.append(
            EmailNotifier(
                env["SMTP_USER"],
                env["SMTP_PASSWORD"],
                env["EMAIL_TO"],
                env.get("SMTP_HOST", "smtp.gmail.com"),
                int(env.get("SMTP_PORT", "465")),
            )
        )
    if not out:
        log.info("No notification channels configured; printing to console")
        out.append(ConsoleNotifier())
    return out


def send_all(notifiers: list[Notifier], method: str, *args) -> int:
    ok = 0
    for n in notifiers:
        try:
            getattr(n, method)(*args)
            ok += 1
        except Exception as exc:
            log.warning("Notifier %s failed: %s", n.name, exc)
    return ok
