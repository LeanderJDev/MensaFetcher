#!/usr/bin/env python3
"""Send an email via SMTP — usable as `--notify-cmd` for `src.ingest`.

This script accepts two positional arguments: `subject` and `body`.
If `body` is omitted the script will read the body text from STDIN.

Configuration is via environment variables:
  - SMTP_HOST (required)
  - SMTP_PORT (optional, default 587)
  - SMTP_USER (optional)
  - SMTP_PASS (optional)
  - SMTP_USE_SSL (optional, '1' or 'true' to use SSL on connect)
  - MAIL_FROM (required)
  - MAIL_TO (required — comma separated list)

Example:
  export SMTP_HOST=smtp.example.com
  export SMTP_PORT=587
  export SMTP_USER=me@example.com
  export SMTP_PASS=secret
  export MAIL_FROM=me@example.com
  export MAIL_TO=me@example.com
  scripts/send_mail.py "Mensa ingest failed" "Traceback..."

Designed to be simple and robust for use from cron or as a notify command.
"""

from __future__ import annotations

import os
import sys
import smtplib
from email.message import EmailMessage
from typing import List
from pathlib import Path
from dotenv import load_dotenv

repo_root = Path(__file__).resolve().parents[1]
env_path = repo_root / ".env"
if env_path.exists():
    load_dotenv(env_path)


def _env_bool(key: str) -> bool:
    v = os.environ.get(key)
    if not v:
        return False
    return v.lower() in ("1", "true", "yes", "on")


def _get_recipients() -> List[str]:
    tos = os.environ.get("MAIL_TO")
    if not tos:
        raise RuntimeError("MAIL_TO environment variable not set")
    return [t.strip() for t in tos.split(",") if t.strip()]


def main(argv: List[str]) -> int:
    if len(argv) < 2:
        print(
            "Usage: send_mail.py <subject> [body]. If body omitted, reads stdin.",
            file=sys.stderr,
        )
        return 2

    subject = argv[1]
    if len(argv) >= 3:
        body = argv[2]
    else:
        body = sys.stdin.read()

    host = os.environ.get("SMTP_HOST")
    if not host:
        print("SMTP_HOST not set", file=sys.stderr)
        return 3
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER")
    pwd = os.environ.get("SMTP_PASS")
    use_ssl = _env_bool("SMTP_USE_SSL") or port == 465

    mail_from = os.environ.get("MAIL_FROM")
    if not mail_from:
        print("MAIL_FROM not set", file=sys.stderr)
        return 4
    try:
        to_addrs = _get_recipients()
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 5

    msg = EmailMessage()
    msg["From"] = mail_from
    msg["To"] = ", ".join(to_addrs)
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        if use_ssl:
            with smtplib.SMTP_SSL(host, port, timeout=30) as s:
                if user and pwd:
                    s.login(user, pwd)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=30) as s:
                s.ehlo()
                # Prefer STARTTLS when available
                try:
                    if s.has_extn("STARTTLS"):
                        s.starttls()
                        s.ehlo()
                except Exception:
                    # Continue without STARTTLS if server doesn't support it
                    pass
                if user and pwd:
                    s.login(user, pwd)
                s.send_message(msg)
    except Exception as exc:
        print(f"Failed to send mail: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
