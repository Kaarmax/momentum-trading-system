#!/usr/bin/env python3
"""
Cron entry point for the quarterly momentum rebalance.

Setup (run once):
    crontab -e

Add this line (adjust paths to match your system):
    35 9 15 3,6,9,12 * cd /Users/xiangrumo/Documents/Quantitative\ Trading\ Systems/momentum && .venv/bin/python rebalance_job.py >> live_trading_data/logs/cron.log 2>&1

This fires at 9:35 AM local time on the 15th of March, June, September, December —
5 minutes after market open to allow normal price discovery.

To use a live account instead of paper, set IBKR_PAPER=false in your .env file.

Email notifications (optional):
    Set EMAIL_FROM, EMAIL_TO, EMAIL_APP_PASSWORD in your .env file.
    See .env.example for instructions.
"""

import logging
import os
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path

from dotenv import load_dotenv
from live_trader import run_live_rebalance

# ============================================================================
# LOGGING
# ============================================================================

LOG_DIR = Path("live_trading_data/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

log_file = LOG_DIR / f"rebalance_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(),
    ],
)

# Redirect print() output to the logger as well
import builtins
_real_print = builtins.print


def _logged_print(*args, **kwargs):
    msg = " ".join(str(a) for a in args)
    logging.info(msg)


builtins.print = _logged_print

# ============================================================================
# EMAIL
# ============================================================================

def _send_email(log_path: Path, success: bool) -> None:
    """Email the rebalance log to EMAIL_TO using Gmail SMTP."""
    email_from = os.getenv("EMAIL_FROM", "")
    email_to   = os.getenv("EMAIL_TO", "")
    app_pw     = os.getenv("EMAIL_APP_PASSWORD", "")

    if not all([email_from, email_to, app_pw]):
        logging.info("Email not configured — skipping notification (set EMAIL_FROM/TO/APP_PASSWORD in .env)")
        return

    status  = "✓ Success" if success else "✗ FAILED"
    subject = f"[Momentum] Quarterly Rebalance {status} — {datetime.now().strftime('%Y-%m-%d')}"

    try:
        body = log_path.read_text()
    except Exception:
        body = "(could not read log file)"

    msg            = MIMEText(body)
    msg["Subject"] = subject
    msg["From"]    = email_from
    msg["To"]      = email_to

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(email_from, app_pw)
            smtp.sendmail(email_from, email_to, msg.as_string())
        logging.info(f"Email sent to {email_to}")
    except Exception as e:
        logging.warning(f"Failed to send email: {e}")


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    load_dotenv()
    paper = os.getenv("IBKR_PAPER", "true").lower() != "false"
    mode = "PAPER" if paper else "LIVE"

    logging.info("=" * 60)
    logging.info(f"Quarterly Rebalance Starting ({mode})")
    logging.info(f"Log: {log_file}")
    logging.info("=" * 60)

    success = False
    try:
        result = run_live_rebalance(paper=paper)
        logging.info("=" * 60)
        logging.info(f"Rebalance Complete: {result}")
        logging.info("=" * 60)
        success = True
    except Exception:
        logging.exception("Rebalance FAILED with unhandled exception")
    finally:
        _send_email(log_file, success)
        if not success:
            raise SystemExit(1)
