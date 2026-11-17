
"""Shared file handling and report content for every messenger."""

import json
import uuid
import zipfile

from pathlib import Path


OPENVPN_FILE = Path("output/selected_servers.json")
SSTP_FILE = Path("output/selected_sstp_servers.json")
OPENVPN_DIR = Path("output/openvpn")

# One archive for every selected config, so a messenger can deliver
# the whole OpenVPN half of the report in a single message.
ARCHIVE_FILE = Path("output/vpngate-openvpn-configs.zip")


def load_servers(path, required=True):

    if not path.exists():

        if required:
            raise FileNotFoundError(
                f"Server list not found: {path}"
            )

        print(f"WARNING: server list missing: {path}")
        return []

    with path.open("r", encoding="utf-8") as file:
        servers = json.load(file)

    if not isinstance(servers, list):
        raise ValueError(f"Invalid server list: {path}")

    return servers


def find_config(server):
    """Locate the generated .ovpn file for a selected server."""

    code = (
        str(server.get("country_code", "Unknown")).strip()
        or "Unknown"
    )

    ip = str(server.get("ip", "")).strip()

    if not ip:
        return None

    candidate = OPENVPN_DIR / f"{code}_{ip}.ovpn"

    return candidate if candidate.exists() else None


def build_archive(servers):
    """Collect every available config into one deliverable file.

    Returns the archive path and the indexes for which no .ovpn file
    could be found, so the caller can still report those servers.
    """

    ARCHIVE_FILE.parent.mkdir(
        parents=True, exist_ok=True
    )

    missing = []
    added = 0

    with zipfile.ZipFile(
        ARCHIVE_FILE, "w", zipfile.ZIP_DEFLATED
    ) as archive:

        for index, server in enumerate(servers, start=1):

            config = find_config(server)

            if config is None:
                missing.append(index)
                continue

            archive.write(config, arcname=config.name)
            added += 1

    if not added:
        ARCHIVE_FILE.unlink(missing_ok=True)
        return None, missing

    return ARCHIVE_FILE, missing


def openvpn_rows(servers):
    """The fields the VPN Gate site itself shows for each server."""

    for index, server in enumerate(servers, start=1):

        yield {
            "index": index,
            "country": str(server.get("country", "Unknown")),
            "ip": str(server.get("ip", "?")),
            "days": server.get("uptime_days"),
            "sessions": server.get("sessions"),
            "session_label": (
                "session" if server.get("sessions") == 1
                else "sessions"
            )
        }


def sstp_rows(servers):
    """Hostname plus whatever differs from the vpn / 443 defaults."""

    for index, server in enumerate(servers, start=1):

        port = server.get("sstp_port", 443)

        username = str(server.get("username", "vpn"))
        password = str(server.get("password", "vpn"))

        custom_login = (
            username != "vpn" or password != "vpn"
        )

        yield {
            "index": index,
            "hostname": str(
                server.get("sstp_hostname", "Unknown")
            ),
            "port": port if port != 443 else None,
            "username": username if custom_login else None,
            "password": password if custom_login else None
        }


def encode_multipart(fields, files):
    """Build a multipart body without a third-party dependency."""

    boundary = uuid.uuid4().hex
    lines = []

    for name, value in fields.items():

        lines.append(f"--{boundary}".encode())
        lines.append(
            (
                f'Content-Disposition: form-data; '
                f'name="{name}"'
            ).encode()
        )
        lines.append(b"")
        lines.append(str(value).encode("utf-8"))

    for name, (filename, content) in files.items():

        lines.append(f"--{boundary}".encode())
        lines.append(
            (
                f'Content-Disposition: form-data; '
                f'name="{name}"; filename="{filename}"'
            ).encode()
        )
        lines.append(b"Content-Type: application/octet-stream")
        lines.append(b"")
        lines.append(content)

    lines.append(f"--{boundary}--".encode())
    lines.append(b"")

    return (
        b"\r\n".join(lines),
        f"multipart/form-data; boundary={boundary}"
    )
