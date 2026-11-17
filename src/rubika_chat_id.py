
"""Find the chat id a Rubika bot can post to.

Rubika has no getChats method, so a chat id can only be learned from
an update: the bot has to receive something first. Send the bot a
message (or post in the group/channel it administers), then run this
script and it prints every chat id it saw.
"""

import json
import os
import sys
import urllib.request


API_URL = "https://botapi.rubika.ir/v3"


def call(token, method, payload):
    request = urllib.request.Request(
        f"{API_URL}/{token}/{method}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def main():
    token = os.getenv("RUBIKA_BOT_TOKEN", "")

    if len(sys.argv) > 1:
        token = sys.argv[1]

    token = token.strip()

    if not token:
        print(
            "Pass the token or set RUBIKA_BOT_TOKEN.\n"
            "  python src/rubika_chat_id.py <token>"
        )
        return 1

    me = call(token, "getMe", {})

    if str(me.get("status", "")).upper() != "OK":
        print(f"Token rejected: {me.get('status')} {me.get('status_det', '')}")
        return 1

    bot = me.get("data", {}).get("bot", {})

    print(
        f"Token is valid. Bot: {bot.get('bot_title')} "
        f"(@{bot.get('username')})"
    )
    print()

    updates = call(token, "getUpdates", {})

    if str(updates.get("status", "")).upper() != "OK":
        print(f"Could not read updates: {updates.get('status')}")
        return 1

    seen = {}

    for update in updates.get("data", {}).get("updates", []):

        for key in ("message", "new_message"):

            message = update.get(key) or {}
            chat_id = message.get("chat_id")

            if not chat_id:
                continue

            sender = message.get("sender_id", "")

            seen.setdefault(chat_id, {
                "sender": sender,
                "text": str(message.get("text", ""))[:40]
            })

    if not seen:
        print("No updates found.")
        print()
        print("Rubika only reveals a chat id through an update, so:")
        print("  1. Open Rubika and send any message to your bot, or")
        print("     add the bot to your group/channel and post there.")
        print("  2. Run this script again.")
        return 1

    print("Chat ids found:")
    print()

    for chat_id, info in seen.items():

        if chat_id.startswith("b"):
            kind = "private"
        elif chat_id.startswith("g"):
            kind = "group"
        elif chat_id.startswith("c"):
            kind = "channel"
        else:
            kind = "unknown"

        print(f"  {chat_id}   ({kind})")

        if info["text"]:
            print(f"      last message: {info['text']}")

    print()
    print("Set the one you want as RUBIKA_CHAT_ID.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
