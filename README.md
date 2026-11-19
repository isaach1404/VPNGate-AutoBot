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

The pipeline runs about hourly via GitHub Actions
(`.github/workflows/scan.yml`) and can also be triggered manually. See
[Schedule](#schedule) for why it does not simply use an hourly cron.

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
| `src/delivery.py` | Shared config lookup and report rows for every messenger |
| `src/telegram_sender.py` | Uploads one `.ovpn` per message, then the SSTP list |
| `src/rubika_sender.py` | Delivers the same files and list to Rubika |
| `src/rubika_chat_id.py` | Prints the chat ids a Rubika bot has seen, for first-time setup |

## Telegram output

OpenVPN servers arrive as **one `.ovpn` file per message**, so each config is a
tap to import in an OpenVPN app. Every caption carries that server's own
details — country, IP, protocol and port, uptime in days, and the live session
count — using only what the VPN Gate site itself shows.

SSTP follows as **one message listing every host**, each with its destination
details on their own lines beneath the hostname:

```
1. vpn520583431.opengw.net (port 1425)
-RU
-IP: 77.35.53.103
-uptime 4.0d
-10 sessions
2. public-vpn-118.opengw.net
-JP
-IP: 219.100.37.87
-uptime 24.0d
-92 sessions
```

Username and password are shown only when they differ from `vpn` / `vpn`, and
the port only when it is not `443`.

A run produces **one notification**. The first message notifies; every file and
list after it is sent silently, so a run with ten configs still buzzes once.

SSTP is a **hostname-only list**. Each hostname sits in a `<code>` block, so
Telegram copies it on tap. Username and password are omitted entirely when they
are the VPN Gate defaults (`vpn` / `vpn`), and the port is omitted when it is
`443`; either appears only when it genuinely differs.

Country coverage is spread on purpose. Servers are interleaved by country code
with **Russia, Japan and the United States first**, so the highest-scoring
country cannot fill every slot. When the site lists more countries than there
are slots, each contributes in turn.

### Rubika

The same files and the same list go to Rubika after Telegram, with identical
content in plain text. Rubika's API puts the token in the URL path and requires
a separate upload step, so `src/rubika_sender.py` reserves an upload URL, posts
each config, then sends the returned `file_id` to the chat.

Both messengers are independent: a Rubika failure never blocks Telegram, and
each raises a non-zero exit when it delivers nothing at all, so a broken token
shows up in the run instead of passing silently.

#### Connecting Rubika

Rubika has **no `getChats` method**, so a chat id cannot be looked up — it is
only revealed through an update the bot receives. Getting connected therefore
takes three steps:

1. Create the bot with [@BotFather](https://rubika.ir/botfather) and copy its
   token.
2. **Send the bot a message** in Rubika — open a chat with it and say anything.
   For a group or channel, add the bot there and post once.
3. Find the resulting chat id:

```bash
python src/rubika_chat_id.py <token>
```

It prints every chat id the bot has seen, labelled `private` (`b…`), `group`
(`g…`) or `channel` (`c…`). Pick the one you want and store it.

A **channel** id only works while the bot is an admin there with *Send
messages*. If that permission is removed, every send starts failing with
`INVALID_ACCESS` — the bot is no longer a member. A **private** chat (your own
account) always works, and is what this repo currently uses.

Add both to GitHub under Settings → Secrets and variables → Actions:

| Secret | Value |
| --- | --- |
| `RUBIKA_BOT_TOKEN` | the token from step 1 |
| `RUBIKA_CHAT_ID` | the id printed in step 3 |

The next run delivers to Rubika after Telegram. Until both exist the step
prints that it is skipping and exits cleanly; a run that *does* send but
delivers nothing fails instead, so a wrong token is visible.

## Schedule

The goal is a scan **about once an hour**. GitHub's scheduler will not deliver
that on its own.

Measured over 85 hours, this repo's scheduled workflow fired only **14 times
instead of ~138**, at random minutes and never on the requested `:07`. Gaps ran
3.5–10.7 hours. That held for `7,37 * * * *`, for `7 * * * *` and for
`*/5 * * * *` alike, and the runs that did fire succeeded with zero queue
delay — so the cron value is not the variable, and no cron can fix it. Moving
to a fresh workflow file restored firing after a stall, but not the rate.

So a scheduled fire is only treated as a **heartbeat**. Each run installs the
VPN clients once, then loops: scan, deliver, sleep until the next hour, repeat
for about five hours, then exit normally. The next fire starts a fresh stretch.
Because this repo is public its runner minutes are unmetered, so the idle
minutes between scans cost nothing. `concurrency` is set so a fire landing
mid-run waits rather than cancelling the run in progress.

In practice that turns roughly three scans a day into roughly twenty. A gap
longer than the ~5-hour stretch (drawn from that 3.5–10.7 hour history) still
leaves a hole until the next fire, which is the one limitation of this design.

Tuning, all in the `Scan and deliver every hour` step:

| Value | Meaning |
| --- | --- |
| `INTERVAL` | Seconds between scan starts (3180 ≈ 53 min, so ~59.7 min cycles) |
| `BUDGET` | Seconds the loop may run before exiting on its own |
| cron line | How often a heartbeat is attempted |
| `timeout-minutes` | Job cap; must stay above `BUDGET` with room for one slow scan |

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
| `RUBIKA_BOT_TOKEN` | Bot token from [@BotFather](https://rubika.ir/botfather) |
| `RUBIKA_CHAT_ID` | Chat, group or channel id the Rubika bot posts to |
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
