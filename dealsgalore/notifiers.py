"""Free notification channels. Each is enabled only when its env vars are set.

  Telegram : TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
  ntfy     : NTFY_TOPIC (pick something unguessable), optional NTFY_SERVER
  Email    : SMTP_USER, SMTP_PASSWORD (Gmail app password), EMAIL_TO,
             optional SMTP_HOST (default smtp.gmail.com), SMTP_PORT (465)
"""
from __future__ import annotations

import html
import logging
import os
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

    @property
    def tag(self) -> str:
        if self.watch_item:
            return f"Watchlist: {self.watch_item}"
        if self.recipient:
            return f"Gift for {self.recipient}"
        return "Deal"

    def lines(self) -> list[str]:
        price = f"${self.price:,.2f}" if self.price is not None else "price ?"
        extra = " · ".join(x for x in (self.reason, self.price_note) if x)
        return [f"{self.tag} — {price} ({self.score:.2f}, {self.source})", self.title, extra]


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
        self.url = f"https://api.telegram.org/bot{token}/sendMessage"
        self.chat_id = chat_id

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
        r.raise_for_status()

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
    name = "ntfy"

    def __init__(self, topic: str, server: str = "https://ntfy.sh"):
        self.endpoint = f"{server.rstrip('/')}/{topic}"

    def _post(self, title: str, body: str, click: str | None = None) -> None:
        headers = {"Title": title.encode("utf-8"), "Tags": "shopping_cart"}
        if click:
            headers["Click"] = click
        requests.post(self.endpoint, data=body.encode("utf-8"), headers=headers, timeout=20).raise_for_status()

    def alert(self, a: Alert) -> None:
        head, title, extra = a.lines()
        self._post(head, f"{title}\n{extra}".strip(), a.url)

    def digest(self, alerts: list[Alert], subject: str) -> None:
        body = "\n\n".join(f"{a.lines()[0]}\n{a.title}\n{a.url}" for a in alerts)
        self._post(subject, body[:3900])


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


def configured_notifiers(dry_run: bool = False) -> list[Notifier]:
    if dry_run:
        return [ConsoleNotifier()]
    env = os.environ
    out: list[Notifier] = []
    if env.get("TELEGRAM_BOT_TOKEN") and env.get("TELEGRAM_CHAT_ID"):
        out.append(TelegramNotifier(env["TELEGRAM_BOT_TOKEN"], env["TELEGRAM_CHAT_ID"]))
    if env.get("NTFY_TOPIC"):
        out.append(NtfyNotifier(env["NTFY_TOPIC"], env.get("NTFY_SERVER", "https://ntfy.sh")))
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
