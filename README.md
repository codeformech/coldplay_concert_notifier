# Coldplay 2027 ticket notifier

Watches for Coldplay's 2027 Europe/UK tour announcement and pushes a Telegram
message when it lands. Runs on a GitHub Actions cron; Claude Haiku screens each
hit so affiliate spam doesn't wake you up.

**Status as of 21 July 2026:** no 2027 dates are officially scheduled. The tour
paused at Wembley on 12 Sep 2025 with Chris Martin saying there were "138 more
shows to go" and that 2027 dates were coming. Everything since has been
re-reporting of that quote. Silence from this bot is the correct output until
that changes.

## How it works

```
GitHub Actions cron (every 30 min)
  ├─ Ticketmaster Discovery API   authoritative, structured, includes presales
  ├─ Google News RSS              fast, noisy, free
  ├─ Claude Haiku                 is this real? is it Europe? write the alert
  ├─ Telegram                     deliver
  └─ state.json                   committed back, so nothing alerts twice
```

**Why not scrape coldplay.com?** It returns HTTP 403 to every non-browser
client — including `/robots.txt` and `/sitemap.xml`. There's no headless path in.
Ticketmaster plus news coverage is the workaround: Ticketmaster is authoritative
but lags the announcement, news is fast but noisy.

**Why Haiku?** The top search results for "Coldplay 2027 tour" are affiliate
pages (`coldplaytour2027.us` and friends) that assert invented specifics like
"exclusive sales begin January 15, 2027". A keyword watcher alerts on those
constantly. Haiku is told today's date and the Wembley backstory, and asked to
distinguish an official announcement from recycled coverage and unsourced
precision. A denylist catches the known offenders first, so the model is the
second line of defence, not the first.

## Setup

You create the credentials — none of them are in this repo, and nothing is
committed but `state.json`.

**1. Telegram bot.** DM [@BotFather](https://t.me/BotFather) → `/newbot` → pick a
name → copy the token.

**2. Your chat id.** Put the token in `.env` (copy `.env.example`), open your
bot, press **Start**, send it any message, then:

```bash
python -m notifier --get-chat-id
```

Telegram only reports a chat once the bot has received something from it, so the
Start step is required. Use this rather than opening
`api.telegram.org/bot<TOKEN>/getUpdates` in a browser — that puts your token in
browser history, which often syncs across devices.

> **If your token is ever exposed** — pasted in a screenshot, committed, shared —
> rotate it: BotFather → `/revoke` → pick the bot. The old token dies
> immediately and you get a new one. Update `.env` and the GitHub secret.

**3. Ticketmaster key.** Register at
[developer.ticketmaster.com](https://developer.ticketmaster.com/) — the Discovery
API key is issued immediately. Free tier is 5000 calls/day; this uses ~720.

**4. Anthropic key.** From the [Claude Console](https://console.anthropic.com/).

**5. GitHub.** Push this repo, then add four **Actions secrets** under
Settings → Secrets and variables → Actions:

| Secret | |
|---|---|
| `TELEGRAM_BOT_TOKEN` | from BotFather |
| `TELEGRAM_CHAT_ID` | from `getUpdates` |
| `TICKETMASTER_API_KEY` | Discovery API |
| `ANTHROPIC_API_KEY` | Claude Console |

## Verifying it works

Locally, put the same four values in a `.env` file (gitignored):

```bash
pip install -r requirements.txt

python tests/check.py                              # 30 offline checks, no keys needed
python -m notifier --test-telegram                 # proves token + chat id
python -m notifier --dry-run                       # poll + screen, send nothing
python -m notifier --dry-run --fixture tests/fixture.json
```

The fixture run is the one that actually tests the judgement. It contains four
items and the expected verdicts are:

| Item | Should alert? |
|---|---|
| The Sept 2025 "138 more shows" tease | **No** — a tease, not dates |
| An affiliate page asserting a Jan 2027 on-sale | **No** — unsourced precision |
| Chris Martin on album plans | **No** — not about touring |
| BBC reporting confirmed 2027 Wembley dates + presale | **Yes** |

If the affiliate item alerts, tighten `CONFIDENCE_THRESHOLD` or add the domain to
`DENYLIST_DOMAINS` in `notifier/config.py`.

Then push, open the **Actions** tab, and hit **Run workflow** to trigger a run by
hand. A green run that commits nothing to `state.json` means it worked and found
nothing — which is correct today.

## Tuning

Everything lives in `notifier/config.py`:

| Setting | Default | |
|---|---|---|
| `COUNTRIES` | 14 European markets | Narrow it to the cities you'd actually travel to |
| `NEWS_MAX_AGE_DAYS` | 14 | Articles older than this are ignored. Measured today, 0 of ~190 feed results were newer than 30 days — this is what keeps the steady state at zero cost |
| `CONFIDENCE_THRESHOLD` | 0.7 | Raise for fewer false alarms, lower to catch more |
| `MAX_CANDIDATES_PER_RUN` | 40 | Anything over the cap is deferred to the next run, never dropped |
| `DENYLIST_DOMAINS` | 11 hosts | Blocked before they reach the API |

Once dates are actually announced, change the cron in
`.github/workflows/watch.yml` to `*/5 * * * *` and trim `COUNTRIES`.

## What this does not do

- **It won't buy the ticket.** It tells you the window is open.
- **GitHub Actions cron drifts** 5–30 minutes, and enforces a 5-minute floor. For
  a general on-sale that clears in minutes, this is a head start on the
  *announcement*, not a guarantee on the *ticket*.
- **Presale registration is usually the real deadline**, often weeks before the
  public on-sale. That's why Ticketmaster's `sales.presales[]` is parsed and the
  soonest presale — not the public on-sale — is what shows up as "Act by".
- **If Coldplay announce only on their own site and socials**, and no outlet
  covers it, nothing here sees it until Ticketmaster listings appear.

## Costs

Haiku 4.5 is $1/$5 per million input/output tokens. A screened item is roughly
500 in + 150 out ≈ $0.00125. Because unchanged items are never re-screened and
the recency filter currently yields zero candidates, the steady-state cost is
effectively zero; a busy announcement week is a few cents. Ticketmaster and
Google News are free.
