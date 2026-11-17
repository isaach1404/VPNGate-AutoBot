
import json
import os
import sys
import time
import urllib.request
import urllib.error
import uuid
from pathlib import Path
from html import escape


OPENVPN_FILE = Path("output/selected_servers.json")
SSTP_FILE = Path("output/selected_sstp_servers.json")
OPENVPN_DIR = Path("output/openvpn")

# Telegram rejects messages longer than 4096 characters.
TELEGRAM_MAX_LENGTH = 3800
CAPTION_MAX_LENGTH = 1000

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
                request,
                timeout=60
            ) as response:

                result = json.loads(
                    response.read().decode("utf-8")
                )

            if not result.get("ok"):
                raise RuntimeError(
                    f"Telegram rejected {method}."
                )

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


def encode_multipart(fields, files):
    boundary = uuid.uuid4().hex
    lines = []

    for name, value in fields.items():

        lines.append(f"--{boundary}".encode())
        lines.append(
            f'Content-Disposition: form-data; name="{name}"'.encode()
        )
        lines.append(b"")
        lines.append(str(value).encode("utf-8"))

    for name, (filename, content) in files.items():

        lines.append(f"--{boundary}".encode())
        lines.append(
            (
                f'Content-Disposition: form-data; name="{name}"; '
                f'filename="{filename}"'
            ).encode()
        )
        lines.append(b"Content-Type: application/octet-stream")
        lines.append(b"")
        lines.append(content)

    lines.append(f"--{boundary}--".encode())
    lines.append(b"")

    return b"\r\n".join(lines), f"multipart/form-data; boundary={boundary}"


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

    content = path.read_bytes()

    result = call_api(
        "sendDocument",
        {
            "chat_id": chat_id,
            "caption": caption,
            "parse_mode": "HTML"
        },
        files={"document": (path.name, content)}
    )

    if result:
        print(f"Sent {path.name}")

    return result is not None


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


def find_config(server):
    """Locate the generated .ovpn file for a selected server."""

    code = str(server.get("country_code", "Unknown")).strip() or "Unknown"
    ip = str(server.get("ip", "")).strip()

    if not ip:
        return None

    candidate = OPENVPN_DIR / f"{code}_{ip}.ovpn"

    return candidate if candidate.exists() else None


def server_line(server):
    """One compact line: country, IP, uptime and sessions."""

    country = str(server.get("country", "Unknown"))
    ip = str(server.get("ip", "?"))
    days = server.get("uptime_days")
    sessions = server.get("sessions")

    details = []

    if days:
        details.append(f"{days}d up")

    if sessions:
        details.append(f"{sessions} sessions")

    suffix = f" ({', '.join(details)})" if details else ""

    return (
        f"<code>{escape(ip)}</code> "
        f"{escape(country)}{escape(suffix)}"
    )


def ovpn_caption(index, server):
    lines = [
        f"<b>{index}. {escape(str(server.get('country', 'Unknown')))}</b>",
        f"IP: <code>{escape(str(server.get('ip', '?')))}</code>",
        (
            f"{escape(str(server.get('protocol', '?')).upper())} "
            f"port {escape(str(server.get('port', '?')))}"
        )
    ]

    days = server.get("uptime_days")
    sessions = server.get("sessions")

    if days:
        lines.append(f"Uptime: {days} days")

    if sessions:
        lines.append(f"Sessions: {sessions}")

    lines.extend([
        "",
        "Open in an OpenVPN app to import."
    ])

    caption = "\n".join(lines)

    if len(caption) > CAPTION_MAX_LENGTH:
        caption = caption[:CAPTION_MAX_LENGTH - 3] + "..."

    return caption


def create_sstp_section(servers):
    """Hostnames only, tappable to copy.

    Username and port are omitted unless they differ from the
    VPN Gate defaults of vpn / 443.
    """

    lines = [
        "<b>SSTP SERVERS</b>",
        f"Selected servers: {len(servers)}",
        ""
    ]

    if not servers:
        lines.append("No reachable SSTP servers found.")
        return lines

    for index, server in enumerate(servers, start=1):

        hostname = str(server.get("sstp_hostname", "Unknown"))
        port = server.get("sstp_port", 443)
        username = str(server.get("username", "vpn"))
        password = str(server.get("password", "vpn"))

        # <code> makes the hostname tappable so Telegram copies it.
        entry = (
            f"{index}. <code>{escape(hostname)}</code>"
        )

        extras = []

        if port != 443:
            extras.append(f"port {port}")

        if username != "vpn" or password != "vpn":
            extras.append(f"user {escape(username)}")
            extras.append(f"pass {escape(password)}")

        if extras:
            entry += f" ({', '.join(extras)})"

        lines.append(entry)

    return lines


def create_header(openvpn_servers, sstp_servers):
    return "\n".join([
        "<b>VPN Gate - Healthy Servers</b>",
        "",
        f"OpenVPN configs: {len(openvpn_servers)} (sent as files)",
        f"SSTP hosts: {len(sstp_servers)}",
        "",
        "<i>An OpenVPN config file follows each of the next "
        "messages.</i>"
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

    header = create_header(openvpn_servers, sstp_servers)

    if send_telegram_message(header):
        delivered += 1

    # OpenVPN servers become downloadable files with a short caption.
    missing_configs = []

    for index, server in enumerate(openvpn_servers, start=1):

        config_path = find_config(server)

        if config_path is None:
            missing_configs.append(index)
            continue

        if send_telegram_document(
            config_path,
            ovpn_caption(index, server)
        ):
            delivered += 1

    # A compact text list for anything whose file was not found, so
    # the server is still usable by hand.
    if missing_configs:

        fallback = [
            "<b>OPENVPN (no config file found)</b>",
            ""
        ]

        for index in missing_configs:

            fallback.append(
                f"{index}. {server_line(openvpn_servers[index - 1])}"
            )

        send_telegram_message("\n".join(fallback))

    for chunk in split_message(
        "\n".join(create_sstp_section(sstp_servers))
    ):

        if send_telegram_message(chunk):
            delivered += 1

    print()
    print("========== TELEGRAM SUMMARY ==========")
    print(f"OpenVPN servers: {len(openvpn_servers)}")
    print(f"OpenVPN files sent: {len(openvpn_servers) - len(missing_configs)}")
    print(f"SSTP servers sent: {len(sstp_servers)}")
    print(f"Messages delivered: {delivered}")

    if missing_configs:
        print(
            f"WARNING: no .ovpn file for {len(missing_configs)} "
            "server(s); listed as text instead."
        )

    print("Telegram delivery completed.")
    print("======================================")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Telegram sending failed: {error}")
        sys.exit(1)
