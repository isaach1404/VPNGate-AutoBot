
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
    build_archive,
    encode_multipart,
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


def send_telegram_message(message):
    _, chat_id = get_token_and_chat()

    result = call_api("sendMessage", {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    })

    if result:
        print("Telegram message sent successfully.")

    return result is not None


def send_telegram_document(path, caption):
    _, chat_id = get_token_and_chat()

    # Captions are capped separately from message length; refuse
    # rather than send a truncated, tag-unbalanced caption.
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
            "parse_mode": "HTML"
        },
        files={
            "document": (path.name, path.read_bytes())
        }
    )

    if result:
        print(f"Sent {path.name}")

    return result is not None


def openvpn_line(row):
    """One line per server: country, IP, uptime and sessions."""

    details = []

    if row["days"]:
        details.append(f"{row['days']}d")

    if row["sessions"]:
        details.append(f"{row['sessions']}s")

    suffix = f" {escape(' · '.join(details))}" if details else ""

    return (
        f"{row['index']}.{escape(row['country'])} "
        f"<code>{escape(row['ip'])}</code>{suffix}"
    )


def create_openvpn_section(servers):
    lines = ["<b>OPENVPN</b>"]

    for row in openvpn_rows(servers):
        lines.append(openvpn_line(row))

    return lines


def create_sstp_section(servers):
    """Hostnames only, tappable to copy."""

    lines = ["<b>SSTP</b>"]

    if not servers:
        lines.append("No reachable SSTP servers found.")
        return lines

    for row in sstp_rows(servers):

        # <code> makes the hostname tappable to copy.
        entry = (
            f"{row['index']}. "
            f"<code>{escape(row['hostname'])}</code>"
        )

        extras = []

        if row["port"]:
            extras.append(f"port {row['port']}")

        if row["username"]:
            extras.append(f"user {escape(row['username'])}")
            extras.append(f"pass {escape(row['password'])}")

        if extras:
            entry += f" ({', '.join(extras)})"

        lines.append(entry)

    return lines


def create_report(openvpn_servers, sstp_servers):
    """Everything in one caption, so a run sends one notification."""

    lines = [
        (
            f"<b>VPN Gate</b> {len(openvpn_servers)} OVPN · "
            f"{len(sstp_servers)} SSTP"
        )
    ]

    if openvpn_servers:
        lines.extend(create_openvpn_section(openvpn_servers))

    lines.extend(create_sstp_section(sstp_servers))

    return "\n".join(lines)


def create_short_caption(openvpn_servers):
    """Used only when the full report is too long for a caption."""

    return "\n".join([
        "<b>VPN Gate - OpenVPN configs</b>",
        f"{len(openvpn_servers)} verified servers in this file.",
        "Tap it, then open with your OpenVPN app."
    ])


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

    # One archive instead of one message per server, so a run does
    # not trigger a burst of notifications.
    archive, missing = (None, [])

    if openvpn_servers:
        archive, missing = build_archive(openvpn_servers)

        if archive is None:
            print(
                "No .ovpn files were found; reporting OpenVPN "
                "servers as text only."
            )

    report = create_report(openvpn_servers, sstp_servers)

    if archive is not None:

        # The whole report rides along as the caption, so the run
        # produces exactly one notification.
        if len(report) <= CAPTION_MAX_LENGTH:

            if send_telegram_document(archive, report):
                delivered += 1

        else:
            if send_telegram_document(
                archive, create_short_caption(openvpn_servers)
            ):
                delivered += 1

            for chunk in split_message(report):

                if send_telegram_message(chunk):
                    delivered += 1

    else:

        for chunk in split_message(report):

            if send_telegram_message(chunk):
                delivered += 1

    print()
    print("========== TELEGRAM SUMMARY ==========")
    print(f"OpenVPN servers: {len(openvpn_servers)}")
    print(
        f"OpenVPN configs in archive: "
        f"{len(openvpn_servers) - len(missing)}"
    )
    print(f"SSTP servers sent: {len(sstp_servers)}")
    print(f"Messages delivered: {delivered}")

    if missing:
        print(
            f"WARNING: no .ovpn file for {len(missing)} "
            "server(s); listed in the text report."
        )

    print("======================================")

    if delivered == 0:
        raise RuntimeError(
            "Telegram accepted nothing; check the token and chat id."
        )

    print("Telegram delivery completed.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Telegram sending failed: {error}")
        sys.exit(1)
