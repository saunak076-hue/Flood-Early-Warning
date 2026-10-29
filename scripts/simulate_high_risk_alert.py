"""
CLI Utility to dispatch a test-only simulated HIGH-risk flood alert to Telegram
for Team C: Flood Early Warning System.

Usage:
    python scripts/simulate_high_risk_alert.py

Features:
- Reads TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID from .env
- Clearly marks the message as a SIMULATED TEST / DRILL ONLY
- Does not create a fake live flood alert on the dashboard or modify active alerts
- Masks bot credentials in console output
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Ensure root directory is in sys.path and .env is loaded
BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"
load_dotenv(dotenv_path=ENV_PATH)
sys.path.insert(0, str(BASE_DIR))

import telegram_notifier


def main():
    print("=" * 65)
    print("  Flood Early Warning — Simulated HIGH-Risk Alert Drill")
    print("=" * 65)

    bot_token, chat_id = telegram_notifier.get_telegram_credentials()
    masked = telegram_notifier.mask_token(bot_token)

    print(f"[*] Configuration Source: {ENV_PATH}")
    print(f"[*] TELEGRAM_CHAT_ID:     {chat_id or '<NOT_SET>'}")
    print(f"[*] TELEGRAM_BOT_TOKEN:   {masked}")

    if not bot_token or not chat_id:
        print("\n[!] ERROR: Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID.")
        print("    Please set both in your .env file in the project root.")
        return 1

    print("\n[*] Dispatching simulated HIGH-risk drill alert to Telegram...")
    result = telegram_notifier.send_simulated_high_risk_alert()

    print("\n" + "-" * 65)
    print("  Delivery Result")
    print("-" * 65)

    if result.get("success"):
        print(f"[+] Status:        DELIVERED (HTTP 200)")
        print(f"[+] Message ID:    {result.get('message_id')}")
        print(f"[+] Notice:        Simulated HIGH-risk drill alert received in Telegram.")
        print(f"[+] Dashboard:     No active flood alert created on dashboard (drill only).")
        print("=" * 65)
        return 0
    else:
        status = result.get("status", "FAILED")
        error_desc = result.get("error", "Unknown error")
        http_code = result.get("http_status")
        print(f"[-] Status:        {status}")
        if http_code:
            print(f"[-] HTTP Code:     {http_code}")
        print(f"[-] Error Details: {error_desc}")
        print("=" * 65)
        return 1


if __name__ == "__main__":
    sys.exit(main())

