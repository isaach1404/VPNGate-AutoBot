
import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
from html import escape


OPENVPN_FILE = Path("output/selected_servers.json")
SSTP_FILE = Path("output/selected_sstp_servers.json")

# Telegram rejects messages longer than 4096 characters.
TELEGRAM_MAX_LENGTH = 3800

RETRY_DELAYS = [5, 15, 30]


def send_telegram_message(message):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        raise RuntimeError("Telegram credentials are missing.")

    url = f"https://api.telegram.org/bot{token}/sendMessage"

    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }

    data = json.dumps(payload).encode("utf-8")

    last_error = None

    for attempt in range(len(RETRY_DELAYS) + 1):

        request = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                result = json.loads(response.read().decode("utf-8"))

            if not result.get("ok"):
                raise RuntimeError(
                    "Telegram API rejected the message."
                )

            print("Telegram message sent successfully.")
            return True

        except urllib.error.HTTPError as error:

            last_error = error

            # 429 = rate limited; retrying is expected.
            if error.code != 429:
                print(f"Telegram HTTP error: {error.code}")
                raise

            print("Telegram rate limit hit; will retry.")

        except urllib.error.URLError as error:

            last_error = error
            print("Could not connect to Telegram API.")

        if attempt < len(RETRY_DELAYS):
            time.sleep(RETRY_DELAYS[attempt])

    print(f"Telegram delivery failed: {last_error}")
    return False


def load_servers(file_path, required=True):

    if not file_path.exists():

        if required:
            raise FileNotFoundError(
                f"Server list not found: {file_path}"
            )

        print(f"WARNING: server list missing: {file_path}")
        return []

    with file_path.open("r", encoding="utf-8") as file:
        servers = json.load(file)

    if not isinstance(servers, list):
        raise ValueError(f"Invalid server list: {file_path}")

    return servers


def create_openvpn_section(servers):
    lines = [
        "<b>OPENVPN SERVERS</b>",
        f"Selected servers: {len(servers)}",
        ""
    ]

    if not servers:
        lines.append("No healthy OpenVPN servers found.")
        return lines

    for index, server in enumerate(servers, start=1):
        hostname = escape(str(server.get("hostname", "Unknown")))
        ip = escape(str(server.get("ip", "Unknown")))
        country = escape(str(server.get("country", "Unknown")))
        protocol = escape(str(server.get("protocol", "Unknown")))
        port = escape(str(server.get("port", "Unknown")))

        lines.extend([
            f"<b>{index}. {hostname}</b>",
            f"Country: {country}",
            f"IP: <code>{ip}</code>",
            f"Protocol: {protocol.upper()}",
            f"Port: {port}",
            ""
        ])

    return lines


def create_sstp_section(servers):
    lines = [
        "<b>SSTP SERVERS</b>",
        f"Selected servers: {len(servers)}",
        ""
    ]

    if not servers:
        lines.append("No reachable SSTP servers found.")
        return lines

    for index, server in enumerate(servers, start=1):
        ip = escape(str(server.get("ip", "Unknown")))
        hostname = escape(str(server.get("sstp_hostname", "Unknown")))
        port = escape(str(server.get("sstp_port", "Unknown")))
        username = escape(str(server.get("username", "vpn")))
        password = escape(str(server.get("password", "vpn")))

        lines.extend([
            f"<b>{index}. {hostname}</b>",
            f"IP: <code>{ip}</code>",
            f"SSTP Hostname: <code>{hostname}</code>",
            f"SSTP Port: <code>{port}</code>",
            f"Username: <code>{username}</code>",
            f"Password: <code>{password}</code>",
            ""
        ])

    return lines


def create_server_message(openvpn_servers, sstp_servers):
    lines = [
        "<b>VPN Gate - Healthy Servers</b>",
        "",
        *create_openvpn_section(openvpn_servers),
        "",
        *create_sstp_section(sstp_servers),
        "",
        "<i>Generated automatically by VPNGate-AutoBot</i>"
    ]

    return "\n".join(lines)


def split_message(message, max_length=TELEGRAM_MAX_LENGTH):
    """Split on line boundaries so HTML tags stay intact."""

    if len(message) <= max_length:
        return [message]

    chunks = []
    current = []

    for line in message.split("\n"):

        candidate_length = len("\n".join(current + [line]))

        if current and candidate_length > max_length:
            chunks.append("\n".join(current))
            current = [line]

        else:
            current.append(line)

    if current:
        chunks.append("\n".join(current))

    return chunks


def main():
    openvpn_servers = load_servers(OPENVPN_FILE, required=False)
    sstp_servers = load_servers(SSTP_FILE, required=False)

    if not openvpn_servers and not sstp_servers:
        print("No healthy servers in either list; nothing to send.")
        return

    message = create_server_message(
        openvpn_servers,
        sstp_servers
    )

    chunks = split_message(message)

    print(
        f"Sending {len(chunks)} Telegram message(s)."
    )

    for index, chunk in enumerate(chunks, start=1):

        if len(chunks) > 1:
            chunk = (
                f"<i>Part {index}/{len(chunks)}</i>\n\n"
                + chunk
            )

        if not send_telegram_message(chunk):
            raise RuntimeError(
                f"Telegram delivery failed at part {index}."
            )

    print()
    print("========== TELEGRAM SUMMARY ==========")
    print(f"OpenVPN servers sent: {len(openvpn_servers)}")
    print(f"SSTP servers sent: {len(sstp_servers)}")
    print(f"Messages sent: {len(chunks)}")
    print("Telegram delivery completed successfully.")
    print("======================================")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Telegram sending failed: {error}")
        sys.exit(1)
