
"""Deliver the same report to Rubika.

Rubika's bot API mirrors Telegram's shape but not its transport:
the token goes in the URL path, files are uploaded to a separate
one-time URL first, and the resulting file_id is then sent to a
chat. Markup is plain text, so no HTML is used here.
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error

from delivery import (
    OPENVPN_FILE,
    SSTP_FILE,
    encode_multipart,
    find_config,
    load_servers,
    openvpn_rows,
    sstp_rows
)


API_URL = "https://botapi.rubika.ir/v3"

MAX_MESSAGE_LENGTH = 3500

RETRY_DELAYS = [5, 15, 30]


def get_credentials():
    token = os.getenv("RUBIKA_BOT_TOKEN")
    chat_id = os.getenv("RUBIKA_CHAT_ID")

    if not token or not chat_id:
        return None, None

    return token, chat_id


def call_api(method, payload):
    token, _ = get_credentials()

    url = f"{API_URL}/{token}/{method}"

    body = json.dumps(payload).encode("utf-8")

    last_error = None

    for attempt in range(len(RETRY_DELAYS) + 1):

        request = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        try:
            with urllib.request.urlopen(
                request, timeout=90
            ) as response:

                result = json.loads(
                    response.read().decode("utf-8")
                )

            status = str(result.get("status", ""))

            if status.upper() not in (
                "OK", "SUCCESS", "SENT"
            ):
                print(
                    f"Rubika rejected {method}: "
                    f"{status} {result.get('status_det', '')}"
                )
                return None

            return result

        except urllib.error.HTTPError as error:

            last_error = error

            detail = ""
            try:
                detail = error.read().decode(
                    "utf-8", "replace"
                )[:300]
            except Exception:
                pass

            print(
                f"Rubika HTTP {error.code} on {method}: {detail}"
            )

        except urllib.error.URLError as error:

            last_error = error
            print(f"Could not reach Rubika API: {error}")

        if attempt < len(RETRY_DELAYS):
            time.sleep(RETRY_DELAYS[attempt])

    print(f"Rubika {method} failed: {last_error}")
    return None


def send_message(text, silent=False):
    _, chat_id = get_credentials()

    payload = {
        "chat_id": chat_id,
        "text": text
    }

    if silent:
        payload["disable_notification"] = True

    result = call_api("sendMessage", payload)

    if result:
        print(
            "Rubika message sent"
            + (" (silent)." if silent else " successfully.")
        )

    return result is not None


def upload_file(path):
    """Three steps: reserve a URL, upload the bytes, keep the id."""

    result = call_api("requestSendFile", {"type": "File"})

    if not result:
        return None

    upload_url = str(
        (result.get("data") or {}).get("upload_url", "")
    )

    if not upload_url:
        print("Rubika did not return an upload URL.")
        return None

    body, content_type = encode_multipart(
        {},
        {"file": (path.name, path.read_bytes())}
    )

    request = urllib.request.Request(
        upload_url,
        data=body,
        headers={"Content-Type": content_type},
        method="POST"
    )

    try:
        with urllib.request.urlopen(
            request, timeout=180
        ) as response:

            uploaded = json.loads(
                response.read().decode("utf-8")
            )

    except (urllib.error.URLError, ValueError) as error:
        print(f"Rubika upload failed: {error}")
        return None

    file_id = str(
        (uploaded.get("data") or {}).get("file_id", "")
    )

    if not file_id:
        print("Rubika upload returned no file_id.")
        return None

    return file_id


def send_file(path, caption, silent=False):
    file_id = upload_file(path)

    if not file_id:
        return False

    _, chat_id = get_credentials()

    payload = {
        "chat_id": chat_id,
        "file_id": file_id,
        "text": caption
    }

    if silent:
        payload["disable_notification"] = True

    result = call_api("sendFile", payload)

    if result:
        print(
            f"Rubika received {path.name}"
            + (" (silent)." if silent else ".")
        )

    return result is not None


def ovpn_caption(row):

    lines = [
        f"{row['index']}. {row['country']}",
        f"IP: {row['ip']}",
        f"{row['protocol']} port {row['port']}"
    ]

    lines.append(f"Uptime: {row['days'] or 0} days")

    lines.append(f"Sessions: {row['sessions'] or 0}")

    return "\n".join(lines)


def create_header(openvpn_count, sstp_count):
    return "\n".join([
        "VPN Gate - Healthy Servers",
        "",
        f"OpenVPN configs: {openvpn_count} (one file each, below)",
        f"SSTP hosts: {sstp_count}",
        "",
        "Tap an .ovpn file, then open it with your OpenVPN app.",
        "",
        "SSTP will follow in the next message."
    ])


def create_sstp_section(servers):

    lines = [
        "SSTP SERVERS",
        f"Selected servers: {len(servers)}",
        ""
    ]

    if not servers:
        lines.append("No reachable SSTP servers found.")
        return lines

    for row in sstp_rows(servers):

        heading = f"{row['index']}. {row['hostname']}"

        if row["port"]:
            heading += f" (port {row['port']})"

        if row["username"]:
            heading += (
                f" (user {row['username']}, "
                f"pass {row['password']})"
            )

        lines.append(heading)

        details = []

        if row["country"]:
            details.append(row["country"])

        if row["ip"]:
            details.append(f"IP: {row['ip']}")

        details.append(f"uptime {row['days'] or 0}d")

        details.append(
            f"{row['sessions'] or 0} {row['session_label']}"
        )

        if details:
            lines.append(f"   {' · '.join(details)}")

    return lines


def split_message(message, max_length=MAX_MESSAGE_LENGTH):

    if len(message) <= max_length:
        return [message]

    chunks = []
    current = []

    for line in message.split("\n"):

        candidate = len("\n".join(current + [line]))

        if current and candidate > max_length:
            chunks.append("\n".join(current))
            current = [line]

        else:
            current.append(line)

    if current:
        chunks.append("\n".join(current))

    return chunks


def main():
    token, chat_id = get_credentials()

    if not token or not chat_id:
        print(
            "Rubika is not configured "
            "(RUBIKA_BOT_TOKEN / RUBIKA_CHAT_ID); skipping."
        )
        return

    openvpn_servers = load_servers(OPENVPN_FILE, required=False)
    sstp_servers = load_servers(SSTP_FILE, required=False)

    if not openvpn_servers and not sstp_servers:
        print("No healthy servers; nothing to send to Rubika.")
        return

    delivered = 0
    missing = []

    # Same rule as Telegram: one notification per run, then silence.
    announced = False

    def announce():
        nonlocal announced
        silent = announced
        announced = True
        return silent

    if send_message(
        create_header(len(openvpn_servers), len(sstp_servers)),
        silent=announce()
    ):
        delivered += 1

    for row, server in zip(
        openvpn_rows(openvpn_servers), openvpn_servers
    ):

        config_path = find_config(server)

        if config_path is None:
            missing.append(row["index"])
            continue

        if send_file(
            config_path,
            ovpn_caption(row),
            silent=announce()
        ):
            delivered += 1

    for chunk in split_message(
        "\n".join(create_sstp_section(sstp_servers))
    ):

        if send_message(chunk, silent=announce()):
            delivered += 1

    print()
    print("========== RUBIKA SUMMARY ==========")
    print(f"OpenVPN servers: {len(openvpn_servers)}")
    print(
        f"OpenVPN files sent: "
        f"{len(openvpn_servers) - len(missing)}"
    )
    print(f"SSTP servers: {len(sstp_servers)}")
    print(f"Messages delivered: {delivered}")
    print("====================================")

    if delivered <= 1:
        raise RuntimeError(
            "Rubika delivered only the header; check the token "
            "and chat id."
        )

    print("Rubika delivery completed.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Rubika sending failed: {error}")
        sys.exit(1)
