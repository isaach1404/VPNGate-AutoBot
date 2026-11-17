
import csv
import io
import json
import os
import time
import urllib.request
import sys

from pathlib import Path

from openvpn import generate_openvpn_configs
from server_tester import test_server


API_URL = "https://www.vpngate.net/api/iphone/"

TARGET_HEALTHY_SERVERS = 10

SELECTED_SERVERS_FILE = "output/selected_servers.json"


def get_env_int(name, default):
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


MAX_SERVERS_TO_TEST = get_env_int(
    "MAX_SERVERS_TO_TEST", 40
)

MAX_TEST_SECONDS = get_env_int(
    "MAX_TEST_SECONDS", 600
)


def get_number(value):
    try:
        return int(value)
    except (ValueError, TypeError):
        return 0


def is_healthy(result):

    if result["config_status"] != "valid":
        return False

    # UDP has no TCP port to probe; the real connection test
    # is the only reliable check for those servers.
    if (
        result["protocol"].startswith("tcp")
        and result["port_status"] != "open"
    ):
        return False

    if result["connection_status"] != "connected":
        return False

    before = result["public_ip_before"]
    after = result["public_ip_after"]

    return (
        before is not None
        and after is not None
        and before != after
    )


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


PREFERRED_COUNTRIES = [
    "RU",
    "JP",
    "US"
]


def order_by_country_variety(
    servers,
    preferred=PREFERRED_COUNTRIES
):
    """Interleave countries so one country cannot fill every slot.

    Servers are grouped by country code, each group keeps the
    existing score order, and groups are consumed round-robin with
    the preferred countries first. A dominant country like Japan
    therefore contributes one server per round instead of ten.
    """

    groups = {}

    for server in servers:

        code = server.get(
            "CountryShort", ""
        ).strip().upper() or "??"

        groups.setdefault(code, []).append(server)

    order = []

    for code in preferred:

        if code in groups:
            order.append(code)

    order.extend(
        code
        for code in groups
        if code not in order
    )

    ordered = []

    while any(groups.get(code) for code in order):

        for code in order:

            bucket = groups.get(code)

            if bucket:
                ordered.append(bucket.pop(0))

    return ordered


def test_all_servers(
    servers,
    target_count=TARGET_HEALTHY_SERVERS,
    max_tested=MAX_SERVERS_TO_TEST,
    max_seconds=MAX_TEST_SECONDS
):

    print()
    print("========== REAL OPENVPN SERVER SELECTION ==========")
    print(
        f"Limits: {max_tested} servers / "
        f"{max_seconds}s wall clock / "
        f"{target_count} healthy target"
    )

    selected_servers = []
    tested_count = 0

    deadline = time.monotonic() + max_seconds

    for server in servers:

        if len(selected_servers) >= target_count:
            break

        if tested_count >= max_tested:
            print(
                f"Reached test limit ({max_tested} servers)."
            )
            break

        if time.monotonic() > deadline:

            print(
                "Reached time limit; stopping test run."
            )
            break

        result = test_server(server)

        tested_count += 1

        print()
        print(
            f"{tested_count}. "
            f"{result['ip']} | "
            f"Country: {result['country']} | "
            f"Ping: {result['ping']} | "
            f"Protocol: {result['protocol']} | "
            f"Port: {result['port']} | "
            f"Port Status: {result['port_status']} | "
            f"Config: {result['config_status']} | "
            f"VPN Connection: {result['connection_status']}"
        )

        if is_healthy(result):

            selected_servers.append({
                "server": server,
                "test_result": result
            })

            print("   SELECTED: Real OpenVPN connection confirmed")

        else:

            print("   REJECTED: Real OpenVPN connection not confirmed")

        print(
            f"Healthy servers found: "
            f"{len(selected_servers)}/{target_count}"
        )

    print()
    print("========== TEST SUMMARY ==========")

    print(f"Total servers available: {len(servers)}")
    print(f"Servers tested: {tested_count}")
    print(f"Real OpenVPN connections confirmed: {len(selected_servers)}")
    print(f"Target servers: {target_count}")

    if len(selected_servers) >= target_count:
        print("Selection status: TARGET REACHED")
    else:
        print("Selection status: NOT ENOUGH VERIFIED SERVERS")

    print("==================================")

    return selected_servers, tested_count


def save_selected_servers(selected_servers):

    output_path = Path(SELECTED_SERVERS_FILE)

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    export_data = []

    for item in selected_servers:

        server = item["server"]
        result = item["test_result"]

        export_data.append({

            "hostname": server.get("HostName", ""),
            "ip": server.get("IP", ""),
            "country": server.get("CountryLong", "Unknown"),
            "country_code": server.get("CountryShort", ""),
            "score": get_number(server.get("Score")),
            "speed": get_number(server.get("Speed")),
            "vpn_ping": get_number(server.get("Ping")),

            # Uptime is milliseconds in the API; the site shows days.
            "uptime_days": round(
                get_number(server.get("Uptime")) / 86_400_000,
                1
            ),
            "sessions": get_number(
                server.get("NumVpnSessions")
            ),

            "protocol": result["protocol"],
            "port": result["port"],
            "ping_test": result["ping"],
            "port_status": result["port_status"],
            "config_status": result["config_status"],

            "connection_status": result["connection_status"],
            "public_ip_before": result["public_ip_before"],
            "public_ip_after": result["public_ip_after"]

        })

    with output_path.open(
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            export_data,
            file,
            ensure_ascii=False,
            indent=4
        )

    print()
    print("========== JSON EXPORT ==========")
    print(f"Selected servers saved: {len(export_data)}")
    print(f"Output file: {output_path}")
    print("=================================")


def main():

    try:

        # Step 1: Fetch VPN Gate servers
        servers = fetch_servers()

        print()
        print("========== VPN GATE RESULTS ==========")
        print(f"Total servers received: {len(servers)}")

        if not servers:
            raise RuntimeError(
                "No servers were returned by the API."
            )

        # Step 2: Count available OpenVPN configurations
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

        # Step 3: Sort by VPN Gate score, then interleave countries
        # so a single country cannot occupy every selected slot.
        servers.sort(
            key=lambda server: get_number(
                server.get("Score")
            ),
            reverse=True
        )

        servers = order_by_country_variety(servers)

        print()
        print("First 10 servers by score:")
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

        # Step 4: Generate OpenVPN files
        generated_files = generate_openvpn_configs(
            servers,
            output_dir="output/openvpn"
        )

        # Step 5: Test real OpenVPN connections
        selected_servers, tested_count = test_all_servers(
            servers,
            target_count=TARGET_HEALTHY_SERVERS
        )

        # Step 6: Save selected servers to JSON
        save_selected_servers(selected_servers)

        # Step 7: Final summary
        print()
        print("========== FINAL SUMMARY ==========")

        print(f"Servers received: {len(servers)}")
        print(f"OpenVPN files generated: {len(generated_files)}")
        print(f"Servers tested: {tested_count}")
        print(f"Real OpenVPN connections confirmed: {len(selected_servers)}")

        print(
            "VPN Gate API, OpenVPN generation "
            "and real connection testing completed."
        )

        print("===================================")

    except Exception as error:

        print()
        print(f"ERROR: {error}")

        sys.exit(1)


if __name__ == "__main__":
    main()
