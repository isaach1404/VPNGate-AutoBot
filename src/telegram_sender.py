
import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path
from html import escape


def send_telegram_message(message):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        raise RuntimeError(
            "Telegram credentials are missing."
        )

    url = (
        f"https://api.telegram.org/bot{token}/sendMessage"
    )

    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }

    data = json.dumps(payload).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=30
        ) as response:
            result = json.loads(
                response.read().decode("utf-8")
            )

        if not result.get("ok"):
            raise RuntimeError(
                "Telegram API rejected the message."
            )

        print("Telegram message sent successfully.")
        return True

    except urllib.error.HTTPError as error:
        print(
            f"Telegram HTTP error: {error.code}"
        )
        raise

    except urllib.error.URLError:
        print("Could not connect to Telegram API.")
        raise


def create_server_message(servers):
    lines = [
        "<b>VPN Gate - Healthy Servers</b>",
        "",
        f"Selected servers: {len(servers)}",
        ""
    ]

    for index, item in enumerate(servers, start=1):
        hostname = escape(str(item.get("hostname", "Unknown")))
        ip = escape(str(item.get("ip", "Unknown")))
        country = escape(str(item.get("country", "Unknown")))
        protocol = escape(str(item.get("protocol", "Unknown")))
        port = escape(str(item.get("port", "Unknown")))

        lines.extend([
            f"<b>{index}. {hostname}</b>",
            f"Country: {country}",
            f"IP: <code>{ip}</code>",
            f"Protocol: {protocol.upper()}",
            f"Port: {port}",
            ""
        ])

    lines.append(
        "<i>Generated automatically by VPNGate-AutoBot</i>"
    )

    return "\n".join(lines)


def main():
    json_path = Path("output/selected_servers.json")

    if not json_path.exists():
        raise FileNotFoundError(
            f"Server list not found: {json_path}"
        )

    with json_path.open(
        "r",
        encoding="utf-8"
    ) as file:
        servers = json.load(file)

    if not isinstance(servers, list) or not servers:
        raise ValueError(
            "Selected server list is empty or invalid."
        )

    message = create_server_message(servers)

    send_telegram_message(message)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Telegram sending failed: {error}")
        sys.exit(1)
