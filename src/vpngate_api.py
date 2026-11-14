
import csv
import io
import urllib.request
import sys

from openvpn import generate_openvpn_configs
from server_tester import test_server


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
        headers={
            "User-Agent": "VPNGate-AutoBot/1.0"
        }
    )

    with urllib.request.urlopen(
        request,
        timeout=30
    ) as response:

        content = response.read().decode(
            "utf-8",
            errors="replace"
        )

    rows = csv.reader(io.StringIO(content))

    header = None
    servers = []

    for row in rows:

        if not row:
            continue

        if header is None:

            first = row[0].strip().lstrip("#")

            if first == "HostName":

                header = [
                    item.strip().lstrip("#")
                    for item in row
                ]

            continue

        if row[0].startswith("#"):
            continue

        if len(row) < len(header):
            continue

        server = dict(zip(header, row))

        ip = server.get("IP", "").strip()
        hostname = server.get("HostName", "").strip()

        if not ip or not hostname:
            continue

        servers.append(server)

    if header is None:
        raise RuntimeError(
            "Could not find VPN Gate CSV header."
        )

    return servers


def test_all_servers(servers):


def test_all_servers(servers, target_count=10):

    print()
    print("========== SERVER SELECTION ==========")

    selected_servers = []
    results = []

    for index, server in enumerate(servers, start=1):

        if len(selected_servers) >= target_count:
            break

        result = test_server(server)
        results.append(result)

        print(
            f"{index}. {result['ip']} | "
            f"Country: {result['country']} | "
            f"Ping: {result['ping']} | "
            f"Protocol: {result['protocol']} | "
            f"Port: {result['port']} | "
            f"Port Status: {result['port_status']} | "
            f"Config: {result['config_status']}"
        )

        is_healthy_tcp = (
            result["config_status"] == "valid"
            and "tcp" in result["protocol"]
            and result["port_status"] == "open"
        )

        if is_healthy_tcp:
            selected_servers.append(result)

            print("   SELECTED: Healthy TCP server")

        else:
            print("   REJECTED: Server not confirmed healthy")

    print()
    print("========== TEST SUMMARY ==========")
    print(f"Servers tested: {len(results)}")
    print(f"Healthy TCP servers selected: {len(selected_servers)}")
    print(f"Target servers: {target_count}")
    print("==================================")

    return selected_servers

def main():

    try:

        # Step 1: Fetch VPN Gate servers
        servers = fetch_servers()

        print()
        print("========== VPN GATE RESULTS ==========")

        print(
            f"Total servers received: {len(servers)}"
        )

        if not servers:
            raise RuntimeError(
                "No servers were returned by the API."
            )

        # Step 2: Count servers with OpenVPN configs
        openvpn_count = sum(
            1
            for server in servers
            if server.get(
                "OpenVPN_ConfigData_Base64",
                ""
            ).strip()
        )

        print(
            f"Servers with OpenVPN config: {openvpn_count}"
        )

        # Step 3: Sort servers by score
        servers.sort(
            key=lambda server: get_number(
                server.get("Score")
            ),
            reverse=True
        )

        print()
        print("First 10 servers:")
        print("-------------------------------------")

        for index, server in enumerate(
            servers[:10],
            start=1
        ):

            print(
                f"{index}. "
                f"{server.get('CountryLong', 'Unknown')} | "
                f"{server.get('IP', '')} | "
                f"Ping: {server.get('Ping', '0')} ms | "
                f"Speed: {server.get('Speed', '0')} | "
                f"Score: {server.get('Score', '0')}"
            )

        # Step 4: Generate OpenVPN configuration files
        generated_files = generate_openvpn_configs(
            servers,
            output_dir="output/openvpn"
        )

        # Step 5: Test VPN servers
        test_results = test_all_servers(servers[:10])

        # Step 6: Final summary
        print()
        print("========== FINAL SUMMARY ==========")

        print(
            f"Servers received: {len(servers)}"
        )

        print(
            f"OpenVPN files generated: {len(generated_files)}"
        )

        print(
            f"Servers tested: {len(test_results)}"
        )

        print(
            "VPN Gate API, OpenVPN generation "
            "and preliminary server testing completed."
        )

        print("===================================")

    except Exception as error:

        print()
        print(f"ERROR: {error}")

        sys.exit(1)


if __name__ == "__main__":
    main()
