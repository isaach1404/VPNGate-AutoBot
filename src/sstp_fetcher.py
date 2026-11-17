
import re
import json
import urllib.request
import ipaddress

from html.parser import HTMLParser
from pathlib import Path


# Official VPN Gate public server list
SSTP_URL = "https://www.vpngate.net/en/"

OUTPUT_FILE = "output/sstp_servers.json"


class VPNGateSSTPParser(HTMLParser):

    def __init__(self):
        super().__init__()

        self.in_row = False
        self.row_parts = []
        self.row_country = ""
        self.servers = []

    def handle_starttag(self, tag, attrs):

        if tag.lower() == "tr" and not self.in_row:
            self.in_row = True
            self.row_parts = []
            self.row_country = ""
            return

        if not self.in_row or tag.lower() != "img":
            return

        # The country is a flag image placed next to the hostname,
        # e.g. src='../images/flags/JP.png'. The flag icons in the
        # site header use a /16/ subdirectory and are skipped.
        if self.row_country:
            return

        for name, value in attrs:

            if name.lower() != "src" or not value:
                continue

            match = re.search(
                r"images/flags/([A-Za-z]{2})\.\w+$",
                value
            )

            if match:
                self.row_country = match.group(1).upper()

    def handle_data(self, data):

        if self.in_row:
            self.row_parts.append(data)

    def handle_endtag(self, tag):

        if tag.lower() != "tr" or not self.in_row:
            return

        self.in_row = False

        row_text = " ".join(self.row_parts)

        row_text = re.sub(
            r"\s+",
            " ",
            row_text
        ).strip()

        self.process_row(row_text)

    def process_row(self, row_text):

        sstp_match = re.search(
            r"SSTP\s*Hostname\s*:\s*"
            r"([A-Za-z0-9.-]+\.opengw\.net)"
            r"(?::(\d{1,5}))?",
            row_text,
            re.IGNORECASE
        )

        if not sstp_match:
            return

        hostname = sstp_match.group(1)

        port_text = sstp_match.group(2)

        port = int(port_text) if port_text else 443

        if not 1 <= port <= 65535:
            return

        ip_matches = re.findall(
            r"(?<![\d.])"
            r"(?:\d{1,3}\.){3}\d{1,3}"
            r"(?![\d.])",
            row_text
        )

        if not ip_matches:
            return

        ip = ip_matches[0]

        try:
            ipaddress.ip_address(ip)
        except ValueError:
            return

        sessions_match = re.search(
            r"(\d[\d,]*)\s+sessions",
            row_text,
            re.IGNORECASE
        )

        uptime_match = re.search(
            r"(\d[\d,]*)\s+days",
            row_text,
            re.IGNORECASE
        )

        self.servers.append({
            "ip": ip,
            "sstp_hostname": hostname,
            "sstp_port": port,
            "country": self.row_country,
            "sessions": (
                int(sessions_match.group(1).replace(",", ""))
                if sessions_match else 0
            ),
            "uptime_days": (
                float(uptime_match.group(1).replace(",", ""))
                if uptime_match else 0
            ),
            "username": "vpn",
            "password": "vpn"
        })


def fetch_sstp_servers():

    print("Connecting to VPN Gate SSTP server list...")

    request = urllib.request.Request(
        SSTP_URL,
        headers={
            "User-Agent": "VPNGate-AutoBot/1.0"
        }
    )

    with urllib.request.urlopen(
        request,
        timeout=30
    ) as response:

        html = response.read().decode(
            "utf-8",
            errors="replace"
        )

    parser = VPNGateSSTPParser()

    parser.feed(html)

    unique_servers = {}

    for server in parser.servers:

        key = (
            server["ip"],
            server["sstp_hostname"],
            server["sstp_port"]
        )

        unique_servers[key] = server

    return list(unique_servers.values())


def save_sstp_servers(servers):

    output_path = Path(OUTPUT_FILE)

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with output_path.open(
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            servers,
            file,
            ensure_ascii=False,
            indent=4
        )


def main():

    servers = fetch_sstp_servers()

    print()
    print("========== SSTP FETCH SUMMARY ==========")

    print(f"SSTP servers found: {len(servers)}")

    for index, server in enumerate(
        servers[:10],
        start=1
    ):

        print(
            f"{index}. "
            f"IP: {server['ip']} | "
            f"Hostname: {server['sstp_hostname']} | "
            f"Port: {server['sstp_port']}"
        )

    save_sstp_servers(servers)

    print()
    print(f"Output file: {OUTPUT_FILE}")
    print("SSTP data collection completed.")
    print("========================================")


if __name__ == "__main__":
    main()
