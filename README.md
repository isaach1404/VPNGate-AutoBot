# VPNGate-AutoBot

Fetches public VPN servers from [VPN Gate](https://www.vpngate.net/), verifies
which ones actually accept a real connection, and delivers the working list to
Telegram on a schedule.

## How it works

```
VPN Gate API  ──►  real OpenVPN connect + public-IP check  ──┐
                                                             ├──►  Telegram
VPN Gate site ──►  real SSTP connect + public-IP check  ─────┘
```

The pipeline runs every 30 minutes via GitHub Actions
(`.github/workflows/vpn_scanner.yml`) and can also be triggered manually.

A server only counts as healthy when the tunnel comes up **and** the public IP
observed through the tunnel differs from the runner's own IP. Reachability
probes alone are not treated as proof.

## Components

| File | Purpose |
| --- | --- |
| `src/vpngate_api.py` | Fetches the VPN Gate CSV API, sorts by score, interleaves countries, selects healthy OpenVPN servers |
| `src/server_tester.py` | Decodes a `.ovpn` config, probes the port, opens the tunnel, checks the exit IP |
| `src/openvpn.py` | Writes decoded configs to `output/openvpn/*.ovpn` |
| `src/sstp_fetcher.py` | Scrapes SSTP hostnames, IPs and countries from the VPN Gate site |
| `src/sstp_tester.py` | Connects over SSTP and verifies the tunnel's exit IP |
| `src/telegram_sender.py` | Uploads each `.ovpn` as a file and sends the SSTP hostname list |

## Telegram output

OpenVPN servers are delivered as **one `.ovpn` file per message**, so importing
is a tap rather than a copy-and-paste. Each caption carries only what the site
shows: destination country, IP, protocol/port, uptime in days and the live
session count. Tapping the file and choosing an OpenVPN app imports it directly.

SSTP is a **hostname-only list**. Each hostname sits in a `<code>` block, so
Telegram copies it on tap. Username and password are omitted entirely when they
are the VPN Gate defaults (`vpn` / `vpn`), and the port is omitted when it is
`443`; either appears only when it genuinely differs.

Country coverage is spread on purpose. Servers are interleaved by country code
with **Russia, Japan and the United States first**, so the highest-scoring
country cannot fill every slot. When the site lists more countries than there
are slots, each contributes in turn.

## Safety properties

- The runner's own network is never taken over: `redirect-gateway` is stripped
  from configs and ignored when pushed, and exit-IP checks are pinned to the
  tunnel interface with `curl --interface`. A full redirect would break the CI
  job's own connectivity.
- Both halves of the scan run with `continue-on-error`, so a failure in one
  does not block delivery of the other.
- Every stage has a wall-clock budget, so a dead server list cannot hang the job.
- Telegram messages and file uploads are retried on rate limits, and long text
  is split on line boundaries so HTML tags stay balanced.

## Configuration

Secrets (Settings → Secrets and variables → Actions):

| Secret | Description |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | Bot token from [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_CHAT_ID` | Target chat or channel ID |

Tuning (environment variables, set in the workflow):

| Variable | Default | Meaning |
| --- | --- | --- |
| `MAX_SERVERS_TO_TEST` | `30` | OpenVPN servers probed per run |
| `MAX_TEST_SECONDS` | `420` | Wall-clock budget for the OpenVPN phase |

Targets are `TARGET_HEALTHY_SERVERS` (OpenVPN, 10) and `TARGET_SERVERS`
(SSTP, 10), both in the respective source files.

## Running locally

Requires Linux with `openvpn`, `sstp-client`, `ppp` and passwordless `sudo`
for those commands:

```
python src/vpngate_api.py
python src/sstp_fetcher.py
python src/sstp_tester.py
python src/telegram_sender.py
```

Outputs land in `output/` (not committed).

## Output

Each run publishes artifacts: the zipped `.ovpn` configs, the selected OpenVPN
servers, and the selected SSTP servers. The same list is sent to Telegram.
