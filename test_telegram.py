"""
Safe Telegram Notification Test Script for Team C: Flood Early Warning System.

Reads TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID from the root .env file,
sends an authorized, clearly labeled test message via the Telegram Bot API,
and prints the actual delivery result without creating a false flood alert
or leaking secrets.
"""

import argparse
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Ensure the root .env is loaded reliably
BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
load_dotenv(dotenv_path=ENV_PATH)

# Reuse existing project modules
try:
    import telegram_notifier
except ImportError:
    sys.path.insert(0, str(BASE_DIR))
    import telegram_notifier


def run_telegram_test(simulate_high_risk: bool = False):
    title = (
        "Flood Early Warning — Simulated HIGH-Risk Alert Verification"
        if simulate_high_risk
        else "Flood Early Warning — Telegram Integration Verification"
    )
    print("=" * 65)
    print(f"  {title}")
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

    if simulate_high_risk:
        print("\n[*] Sending test-only simulated HIGH-risk alert to Telegram...")
        result = telegram_notifier.send_simulated_high_risk_alert()
    else:
        print("\n[*] Sending clearly labeled test notification...")
        result = telegram_notifier.send_test_notification()

    print("\n" + "-" * 65)
    print("  Delivery Result")
    print("-" * 65)

    if result.get("success"):
        msg_id = result.get("message_id")
        print(f"[+] Status:        DELIVERED (HTTP 200)")
        print(f"[+] Message ID:    {msg_id}")
        if simulate_high_risk:
            print(f"[+] Notice:        Simulated HIGH-risk drill alert received in Telegram.")
            print(f"[+] Dashboard:     No active flood alert created (drill verification only).")
        else:
            print(f"[+] Notice:        Authorized test notification received in Telegram.")
            print(f"[+] Dashboard:     No false flood alerts were created.")
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
    parser = argparse.ArgumentParser(description="Test Telegram integration or dispatch simulated alert drill.")
    parser.add_argument(
        "--simulate-high-risk",
        action="store_true",
        help="Generate a test-only simulated HIGH-risk alert and send to Telegram without creating live dashboard alerts."
    )
    args = parser.parse_args()
    sys.exit(run_telegram_test(simulate_high_risk=args.simulate_high_risk))


