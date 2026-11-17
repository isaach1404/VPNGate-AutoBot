
import json
import os
import sys
import time
import urllib.request
import urllib.error

from pathlib import Path
from html import escape

from delivery import (
    OPENVPN_FILE,
    SSTP_FILE,
    encode_multipart,
    find_config,
    load_servers,
    openvpn_rows,
    sstp_rows
)


# Telegram rejects messages longer than 4096 characters.
TELEGRAM_MAX_LENGTH = 3800
CAPTION_MAX_LENGTH = 1024

RETRY_DELAYS = [5, 15, 30]


def get_token_and_chat():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        raise RuntimeError("Telegram credentials are missing.")

    return token, chat_id


def call_api(method, payload, files=None):
    """POST to a Telegram Bot API method, retrying on 429/network."""

    token, _ = get_token_and_chat()

    url = f"https://api.telegram.org/bot{token}/{method}"

    if files:
        body, content_type = encode_multipart(payload, files)
    else:
        body = json.dumps(payload).encode("utf-8")
        content_type = "application/json"

    last_error = None

    for attempt in range(len(RETRY_DELAYS) + 1):

        request = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": content_type},
            method="POST"
        )

        try:
            with urllib.request.urlopen(
                request, timeout=90
            ) as response:

                result = json.loads(
                    response.read().decode("utf-8")
                )

            if not result.get("ok"):
                print(
                    f"Telegram rejected {method}: "
                    f"{str(result.get('description'))[:200]}"
                )
                return None

            return result

        except urllib.error.HTTPError as error:

            last_error = error

            if error.code != 429:
                detail = ""
                try:
                    detail = error.read().decode(
                        "utf-8", "replace"
                    )[:300]
                except Exception:
                    pass
                print(
                    f"Telegram HTTP {error.code} on {method}: "
                    f"{detail}"
                )
                return None

            print("Telegram rate limit hit; will retry.")

        except urllib.error.URLError as error:

            last_error = error
            print(f"Could not reach Telegram API: {error}")

        if attempt < len(RETRY_DELAYS):
            time.sleep(RETRY_DELAYS[attempt])

    print(f"Telegram {method} failed: {last_error}")
    return None


def send_telegram_message(message, silent=False):
    """silent=True delivers without a notification sound or banner."""

    _, chat_id = get_token_and_chat()

    result = call_api("sendMessage", {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
        "disable_notification": silent
    })

    if result:
        print(
            "Telegram message sent"
            + (" (silent)." if silent else " successfully.")
        )

    return result is not None


def send_telegram_document(path, caption, silent=False):
    _, chat_id = get_token_and_chat()

    if len(caption) > CAPTION_MAX_LENGTH:
        raise ValueError(
            f"Caption is {len(caption)} characters, over the "
            f"{CAPTION_MAX_LENGTH} limit."
        )

    result = call_api(
        "sendDocument",
        {
            "chat_id": chat_id,
            "caption": caption,
            "parse_mode": "HTML",
            "disable_notification": silent
        },
        files={
            "document": (path.name, path.read_bytes())
        }
    )

    if result:
        print(
            f"Sent {path.name}"
            + (" (silent)." if silent else ".")
        )

    return result is not None


def ovpn_caption(row):
    """Country, IP, protocol/port, uptime and sessions."""

    lines = [
        f"{row['index']}. {escape(row['country'])}",
        f"IP: <code>{escape(row['ip'])}</code>",
        f"{escape(row['protocol'])} port {escape(str(row['port']))}"
    ]

    lines.append(
        f"Uptime: {row['days'] or 0} days"
    )

    lines.append(
        f"Sessions: {row['sessions'] or 0}"
    )

    return "\n".join(lines)


def create_header(openvpn_count, sstp_count):
    return "\n".join([
        "<b>VPN Gate - Healthy Servers</b>",
        "",
        f"OpenVPN configs: {openvpn_count} (one file each, below)",
        f"SSTP hosts: {sstp_count}",
        "",
        "<i>Tap an .ovpn file, then open it with your OpenVPN app "
        "to import it.</i>"
    ])


def create_sstp_section(servers):
    """One block per host: hostname plus its destination details."""

    lines = [
        "<b>SSTP SERVERS</b>",
        f"Selected servers: {len(servers)}",
        ""
    ]

    if not servers:
        lines.append("No reachable SSTP servers found.")
        return lines

    for row in sstp_rows(servers):

        # <code> makes the hostname tappable to copy.
        heading = (
            f"{row['index']}. "
            f"<code>{escape(row['hostname'])}</code>"
        )

        if row["port"]:
            heading += f" (port {row['port']})"

        if row["username"]:
            heading += (
                f" (user {escape(row['username'])}, "
                f"pass {escape(row['password'])})"
            )

        lines.append(heading)

        details = []

        if row["country"]:
            details.append(escape(row["country"]))

        if row["ip"]:
            details.append(f"IP: {escape(row['ip'])}")

        if row["days"]:
            details.append(f"uptime {row['days']}d")

        if row["sessions"]:
            details.append(
                f"{row['sessions']} {row['session_label']}"
            )

        if details:
            lines.append(f"   {' · '.join(details)}")

    return lines


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

    delivered = 0
    missing = []

    # Only the first message is allowed to notify; every report that
    # follows is silent, so a run buzzes once no matter how many
    # files or chunks it takes.
    announced = False

    def announce():
        nonlocal announced
        silent = announced
        announced = True
        return silent

    if send_telegram_message(
        create_header(len(openvpn_servers), len(sstp_servers)),
        silent=announce()
    ):
        delivered += 1

    # One file per server, each captioned with that server's details.
    for row, server in zip(
        openvpn_rows(openvpn_servers), openvpn_servers
    ):

        config_path = find_config(server)

        if config_path is None:
            missing.append(row["index"])
            continue

        if send_telegram_document(
            config_path,
            ovpn_caption(row),
            silent=announce()
        ):
            delivered += 1

    if missing:

        fallback = [
            "<b>OPENVPN (no config file found)</b>"
        ]

        for row in openvpn_rows(openvpn_servers):

            if row["index"] in missing:

                fallback.append(
                    f"{row['index']}. {escape(row['country'])} "
                    f"<code>{escape(row['ip'])}</code>"
                )

        if send_telegram_message(
            "\n".join(fallback), silent=announce()
        ):
            delivered += 1

    for chunk in split_message(
        "\n".join(create_sstp_section(sstp_servers))
    ):

        if send_telegram_message(chunk, silent=announce()):
            delivered += 1

    print()
    print("========== TELEGRAM SUMMARY ==========")
    print(f"OpenVPN servers: {len(openvpn_servers)}")
    print(
        f"OpenVPN files sent: "
        f"{len(openvpn_servers) - len(missing)}"
    )
    print(f"SSTP servers sent: {len(sstp_servers)}")
    print(f"Messages delivered: {delivered}")

    if missing:
        print(
            f"WARNING: no .ovpn file for {len(missing)} "
            "server(s); listed as text instead."
        )

    print("======================================")

    if delivered <= 1:
        raise RuntimeError(
            "Telegram delivered only the header; check the token "
            "and chat id."
        )

    print("Telegram delivery completed.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Telegram sending failed: {error}")
        sys.exit(1)
