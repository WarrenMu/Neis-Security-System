from __future__ import annotations

import os
import smtplib
import time
from dataclasses import asdict
from email.message import EmailMessage
from typing import Optional, Protocol

import requests
from loguru import logger

from .pipeline import DetectionEvent


class Notifier(Protocol):
    def send(self, event: DetectionEvent) -> None: ...


class ConsoleNotifier:
    def send(self, event: DetectionEvent) -> None:
        logger.info("ALERT: {}", _event_payload(event))


class WebhookNotifier:
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def send(self, event: DetectionEvent) -> None:
        try:
            requests.post(self.webhook_url, json=_event_payload(event), timeout=5)
        except Exception:
            logger.exception("Webhook notify failed")


class EmailNotifier:
    """SMTP email notifier.

    This is intentionally rate-limited via `RateLimitedNotifier` in `notifier_from_env()`
    to avoid spamming.
    """

    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        smtp_user: Optional[str],
        smtp_pass: Optional[str],
        email_from: str,
        email_to: str,
    ):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_pass = smtp_pass
        self.email_from = email_from
        self.email_to = email_to

    def send(self, event: DetectionEvent) -> None:
        payload = _event_payload(event)

        msg = EmailMessage()
        msg["Subject"] = f"GateWatch alert: {event.subject.value}/{event.arrival.value}"
        msg["From"] = self.email_from
        msg["To"] = self.email_to
        msg.set_content(str(payload))

        with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=10) as s:
            try:
                s.starttls()
            except Exception:
                # Some servers may not support starttls; proceed best-effort.
                pass
            if self.smtp_user and self.smtp_pass:
                s.login(self.smtp_user, self.smtp_pass)
            s.send_message(msg)


class TwilioWhatsAppNotifier:
    """Send WhatsApp messages via Twilio REST API.

    Requires env:
    - GATEWATCH_TWILIO_ACCOUNT_SID
    - GATEWATCH_TWILIO_AUTH_TOKEN
    - GATEWATCH_TWILIO_WHATSAPP_FROM (e.g. whatsapp:+14155238886)
    - GATEWATCH_TWILIO_WHATSAPP_TO (e.g. whatsapp:+15551234567)
    """

    def __init__(self, account_sid: str, auth_token: str, from_: str, to: str):
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.from_ = from_
        self.to = to

    def send(self, event: DetectionEvent) -> None:
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Messages.json"
        payload = _event_payload(event)

        # Keep the message short; include plate if available.
        plate = payload.get("plate_text")
        body = f"GateWatch: {payload['camera_id']} {payload['subject']}/{payload['arrival']}"
        if plate:
            body += f" plate={plate}"

        try:
            resp = requests.post(
                url,
                data={"From": self.from_, "To": self.to, "Body": body},
                auth=(self.account_sid, self.auth_token),
                timeout=10,
            )
            if resp.status_code >= 400:
                logger.error("Twilio WhatsApp notify failed: status={} body={}", resp.status_code, resp.text)
        except Exception:
            logger.exception("Twilio WhatsApp notify failed")


class CompositeNotifier:
    def __init__(self, notifiers: list[Notifier]):
        self._notifiers = notifiers

    def send(self, event: DetectionEvent) -> None:
        for n in self._notifiers:
            try:
                n.send(event)
            except Exception:
                logger.exception("Notifier failed: {}", n.__class__.__name__)


class RateLimitedNotifier:
    """Simple in-memory cooldown to avoid spamming.

    Note: cooldown state resets when the process restarts.
    """

    def __init__(self, inner: Notifier, cooldown_seconds: int):
        self._inner = inner
        self._cooldown_seconds = max(0, int(cooldown_seconds))
        self._last_sent_ts = 0.0

    def send(self, event: DetectionEvent) -> None:
        if self._cooldown_seconds <= 0:
            self._inner.send(event)
            return

        now = time.time()
        if now - self._last_sent_ts < self._cooldown_seconds:
            return

        self._last_sent_ts = now
        self._inner.send(event)


def notifier_from_env() -> Notifier:
    """Build a notifier chain.

    Always includes console logging.
    Optionally adds webhook, WhatsApp (Twilio), and email (rate-limited).
    """

    notifiers: list[Notifier] = [ConsoleNotifier()]

    webhook = os.getenv("GATEWATCH_WEBHOOK_URL")
    if webhook:
        notifiers.append(WebhookNotifier(webhook))

    # WhatsApp via Twilio
    sid = os.getenv("GATEWATCH_TWILIO_ACCOUNT_SID")
    token = os.getenv("GATEWATCH_TWILIO_AUTH_TOKEN")
    wa_from = os.getenv("GATEWATCH_TWILIO_WHATSAPP_FROM")
    wa_to = os.getenv("GATEWATCH_TWILIO_WHATSAPP_TO")
    if sid and token and wa_from and wa_to:
        cooldown = int(os.getenv("GATEWATCH_WHATSAPP_COOLDOWN_SEC", "30"))
        notifiers.append(RateLimitedNotifier(TwilioWhatsAppNotifier(sid, token, wa_from, wa_to), cooldown))

    # Email (optional)
    smtp_host = os.getenv("GATEWATCH_SMTP_HOST")
    email_to = os.getenv("GATEWATCH_EMAIL_TO")
    email_from = os.getenv("GATEWATCH_EMAIL_FROM")
    if smtp_host and email_to and email_from:
        smtp_port = int(os.getenv("GATEWATCH_SMTP_PORT", "587"))
        smtp_user = os.getenv("GATEWATCH_SMTP_USER")
        smtp_pass = os.getenv("GATEWATCH_SMTP_PASS")
        cooldown = int(os.getenv("GATEWATCH_EMAIL_COOLDOWN_SEC", "300"))
        notifiers.append(
            RateLimitedNotifier(
                EmailNotifier(
                    smtp_host=smtp_host,
                    smtp_port=smtp_port,
                    smtp_user=smtp_user,
                    smtp_pass=smtp_pass,
                    email_from=email_from,
                    email_to=email_to,
                ),
                cooldown,
            )
        )

    return CompositeNotifier(notifiers)


def _event_payload(event: DetectionEvent) -> dict[str, object]:
    # asdict() handles dataclass; normalize enums
    d = asdict(event)
    d["ts_utc"] = event.ts_utc.isoformat()
    d["subject"] = event.subject.value
    d["arrival"] = event.arrival.value
    return d
