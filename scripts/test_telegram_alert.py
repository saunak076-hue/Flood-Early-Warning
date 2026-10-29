"""
CLI Utility to test Telegram alert delivery for Team C: Flood Early Warning System.

Usage:
    python scripts/test_telegram_alert.py
"""

import sys
import os

# Add parent directory to path so imports work seamlessly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import telegram_notifier


def main():
    print("=" * 60)
    print("  Flood Early Warning — Telegram Notification Test Utility")
    print("=" * 60)
    
    token, chat_id = telegram_notifier.get_telegram_credentials()
    print(f"[*] Target Chat ID:  {chat_id or '<NOT CONFIGURED>'}")
    print(f"[*] Bot Token:        {telegram_notifier.mask_token(token)}")
    
    if not token or not chat_id:
        print("\n[!] ERROR: Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID in environment or .env file.")
        print("    Configure both variables in your .env file and retry.")
        sys.exit(1)

    print("\n[*] Sending authorized test notification...")
    result = telegram_notifier.send_test_notification()
    
    if result.get("success"):
        print("[+] SUCCESS: Telegram test message delivered successfully!")
        print(f"    Message ID: {result.get('message_id')}")
        print("    Check your Telegram chat for the incoming notification.")
    else:
        print("[-] FAILED: Delivery failed.")
        print(f"    Status: {result.get('status')}")
        print(f"    Error:  {result.get('error')}")
        sys.exit(2)


if __name__ == "__main__":
    main()

