
import csv
import io
import urllib.request
import sys

API_URL = "https://www.vpngate.net/api/iphone/"


def get_number(value):
    try:
        return int(value)
    except (ValueError, TypeError):
        return 0


def fetch_servers():
    print("Connecting to VPN Gate API...")

    request = urllib.request.Request(
        API_URL,
        headers={"User-Agent": "VPNGate-AutoBot/1.0"}
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        content = response.read().decode("utf-8", errors="replace")

    rows = csv.reader(io.StringIO(content))

    header = None
    servers = []

    for row in rows:
        if not row:
            continue

        # Find the CSV header
        if header is None:
            first = row[0].strip().lstrip("#")

            if first == "HostName":
                header = [item.strip().lstrip("#") for item in row]
            continue

        # Ignore comments and incomplete rows
        if row[0].startswith("#") or len(row) < len(header):
            continue

        server = dict(zip(header, row))

        ip = server.get("IP", "").strip()
        hostname = server.get("HostName", "").strip()

        if not ip or not hostname:
            continue

        servers.append(server)

    if header is None:
        raise RuntimeError("Could not find VPN Gate CSV header.")

    return servers


def main():
    try:
        servers = fetch_servers()

        print()
        print("========== VPN GATE RESULTS ==========")
        print(f"Total servers received: {len(servers)}")

        if not servers:
            print("No servers were returned by the API.")
            sys.exit(1)

        openvpn_count = sum(
            1 for server in servers
            if server.get("OpenVPN_ConfigData_Base64", "").strip()
        )

        print(f"Servers with OpenVPN config: {openvpn_count}")
        print()
        print("First 10 servers:")
        print("-------------------------------------")

        servers.sort(
            key=lambda server: get_number(server.get("Score")),
            reverse=True
        )

        for index, server in enumerate(servers[:10], start=1):
            print(
                f"{index}. "
                f"{server.get('CountryLong', 'Unknown')} | "
                f"{server.get('IP', '')} | "
                f"Ping: {server.get('Ping', '0')} ms | "
                f"Speed: {server.get('Speed', '0')} | "
                f"Score: {server.get('Score', '0')}"
            )

        print("-------------------------------------")
        print("VPN Gate API test completed successfully.")

    except Exception as error:
        print(f"ERROR: {error}")
        sys.exit(1)


if __name__ == "__main__":
    main()
