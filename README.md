# 🤖 Botesh — Upwork Job Scraper Discord Bot

A production-grade, real-time Upwork job scraper that posts new job listings directly to your Discord server. Built with Cloudflare bypass, smart token management, and a modular async architecture.

---

## ✨ Features

- 🔍 **Real-time Job Alerts** — Scrapes Upwork every 30 seconds and posts new jobs to dedicated Discord channels
- 🧠 **Intelligent Token Management** — Auto-detects expired tokens and refreshes via headless SeleniumBase (browser launched only once per refresh cycle)
- 🛡️ **Cloudflare Bypass** — Uses `curl_cffi` with Chrome TLS fingerprinting and SeleniumBase with undetected Chrome mode
- 🔒 **Zero Duplicate Alerts** — SQLite-backed deduplication ensures every job is posted exactly once
- 📊 **Rich Discord Embeds** — Each job post includes budget, experience level, proposals count, client details, payment verification, and more
- 📁 **Thread-per-Job** — Every job listing automatically creates its own Discord thread with full details
- 📈 **Memory Monitoring** — Active RSS memory tracking with threshold alerts via `psutil`
- 📝 **Dual-Stream Logging** — All output is simultaneously printed to terminal and saved to `bot.log` with timestamps

---

## 🗂️ Project Structure

```
Botesh/
├── discord_bot.py       # Main bot engine: Discord commands, embeds, scrape loop
├── auth_manager.py      # Token lifecycle: SeleniumBase extraction, caching, thread safety
├── scraper.py           # Upwork GraphQL API queries, curl_cffi HTTP engine
├── database.py          # SQLite helper: job deduplication, target management
├── main.py              # Alternative entry point
├── config.json          # Bot configuration (prefix, guild ID, etc.)
├── .env                 # Secret credentials (DO NOT commit)
├── .gitignore           # Git exclusions
├── bot.log              # Auto-generated live log file
└── jobs.db              # Auto-generated SQLite database
```

---

## 🏗️ Architecture

```
                  ┌─────────────────────────────────────┐
                  │          discord_bot.py             │
                  │  (Async Bot Engine + Task Loop)     │
                  └────────────────────┬────────────────┘
                                       │
        ┌──────────────────────────────┼──────────────────────────────┐
        ▼                              ▼                              ▼
┌──────────────┐               ┌──────────────┐               ┌──────────────┐
│  database.py │               │auth_manager.py│              │  scraper.py  │
│ (SQLite DB)  │               │(SeleniumBase) │              │ (curl_cffi)  │
└──────────────┘               └──────────────┘               └──────────────┘
        │                              │                              │
        ▼                              ▼                              ▼
   jobs.db (Disk)          session_cache.json              Upwork GraphQL API
```

### Component Responsibilities

| File | Responsibility |
|:-----|:--------------|
| `discord_bot.py` | Discord event loop, command handlers, embed formatting, job thread creation |
| `auth_manager.py` | Token extraction via SeleniumBase, 15s concurrency lock, 11h disk caching |
| `scraper.py` | GraphQL queries, curl_cffi TLS fingerprinting, exponential backoff retries |
| `database.py` | SQLite CRUD: tracked targets, seen job IDs, automatic 30-day pruning |

---

## 🔄 Data Flow

```
[1. Loop Triggered (every 30 seconds)]
              │
              ▼
[2. Read All Active Targets from SQLite DB]
              │
              ▼
[3. Run All Targets Concurrently (asyncio.gather)]
              │
              ├── Target 1: 'python'  → Channel: #python-jobs
              ├── Target 2: 'react'   → Channel: #react-jobs
              └── Target 3: 'ai'      → Channel: #ai-jobs
              │
              ▼
[4. Query Upwork GraphQL Search API via curl_cffi]
              │
         ┌────┴────────────────────────┐
         │ 200 OK?                     │ 401 / Permission Error
         ▼                             ▼
[5. Filter New Jobs]           [AuthManager: Refresh Token]
   └── SQLite deduplication      └── Launch 1x SeleniumBase
   └── Strict keyword match      └── Extract UniversalSearchNuxt_vt
   └── RegEx word boundary       └── Save to session_cache.json
              │                   └── Retry search
              ▼
[6. Fetch Client Details (jobPubDetails GraphQL)]
   └── Location, total spent, hire rate, member since
              │
              ▼
[7. Post to Discord]
   └── Send rich embed in channel
   └── Create thread for full job details
   └── Mark job ID as seen in SQLite DB
```

---

## ⚙️ Installation & Setup

### 1. Clone the Repository
```bash
git clone https://github.com/your-username/botesh.git
cd botesh
```

### 2. Create a Virtual Environment
```bash
python -m venv venv
venv\Scripts\activate       # Windows
source venv/bin/activate    # Linux / macOS
```

### 3. Install Dependencies
```bash
pip install discord.py python-dotenv seleniumbase curl_cffi psutil
```

### 4. Configure Environment Variables
Create a `.env` file in the root directory:
```env
DISCORD_TOKEN=your_discord_bot_token_here
DISCORD_CHANNEL_ID=your_default_channel_id_here
UPWORK_SEARCH_QUERY=python
UPWORK_BEARER_TOKEN=your_upwork_bearer_token_here
```

> **⚠️ Warning:** Never commit your `.env` file. It is excluded by `.gitignore`.

### 5. Configure the Bot
Edit `config.json` for bot settings:
```json
{
  "prefix": "!",
  "guild_id": 1234567890
}
```

### 6. Run the Bot
```bash
python discord_bot.py
```

---

## 🎮 Discord Commands

| Command | Description | Example |
|:--------|:------------|:--------|
| `!search <keyword>` | Creates a new Discord channel and registers keyword tracking | `!search flutter` |
| `!track <keyword>` | Binds the **current channel** to a keyword (no new channel created) | `!track react native` |
| `!untrack` | Removes the current channel from active tracking | `!untrack` |
| `!create <name>` | Creates a Discord channel without registering any keyword | `!create test-channel` |
| `!delete [channel]` | Deletes the specified channel (or current channel if omitted) | `!delete react-jobs` |
| `!targets` / `!list` | Lists all active tracked channels and their keywords | `!targets` |

---

## 🔐 Token Management System

The bot handles Upwork authentication through a 3-layer token management strategy:

### Layer 1: Session Cache (Cold Start)
On startup, the bot loads `session_cache.json` if it exists and is less than 11 hours old, allowing instant startup without launching a browser.

```json
{
  "token": "oauth2v2_int_...",
  "cookies": { "cf_clearance": "...", "UniversalSearchNuxt_vt": "..." },
  "timestamp": "2026-07-21T16:00:00"
}
```

### Layer 2: Concurrency Lock (Token Refresh)
When a `401 Unauthorized` is detected, a `threading.Lock()` with a 15-second guard prevents multiple concurrent workers from launching multiple browser instances:

```python
with self.lock:
    # Only 1 worker launches SeleniumBase.
    # All other concurrent workers wait and reuse the fresh token.
    if self.token_timestamp and elapsed < 15:
        return self.last_cookies, self.last_token
```

### Layer 3: Token Scope Selection
Upwork provides two guest tokens. The bot specifically extracts **`UniversalSearchNuxt_vt`** (full OAuth2 job search scope) and ignores `visitor_topnav_gql_token` (navigation-only, insufficient permissions).

---

## 🛡️ Error Handling

| Error | Handling Strategy |
|:------|:-----------------|
| `401 Unauthorized` | Triggers automatic token refresh via SeleniumBase |
| `GraphQL permission error` | Retries with fresh `UniversalSearchNuxt_vt` token |
| Network drop | Exponential backoff: retries at 1s, 2s, 4s delays |
| Discord `429 Rate Limit` | Reads `retry_after` payload and waits before retrying |
| Chrome lock file | Kills lingering `chromedriver.exe` and removes `SingletonLock` |
| High memory (>500 MB) | Logs `⚠️ WARNING: High memory usage detected` |

---

## 📊 Logging System

All output is captured by `LoggerTee` — a custom dual-stream writer:
- **Terminal:** Live output with real-time updates
- **`bot.log`:** Persistent timestamped log file for post-mortem debugging

### Log Emoji Reference

| Emoji | Category |
|:------|:---------|
| 💾 | Session cache loaded/saved |
| 🔄 | Token refresh triggered |
| 🔑 | Token successfully extracted |
| 🔍 | Search target being processed |
| ✅ | Job fetched and posted |
| ⏭️ | Job skipped (already seen) |
| ⚠️ | Non-fatal warning |
| ❌ | Error encountered |
| 📊 | Memory usage report |
| 📌 | Database operation |

---

## 🔧 Technical Stack

| Component | Library | Purpose |
|:----------|:--------|:--------|
| Discord API | `discord.py` | Bot events, commands, embeds, threads |
| HTTP Engine | `curl_cffi` | Chrome TLS fingerprinting for Cloudflare bypass |
| Browser Automation | `seleniumbase` | Headless Chrome for token extraction |
| Database | `sqlite3` (stdlib) | Job deduplication and target management |
| Memory Monitoring | `psutil` | Real-time process RSS memory tracking |
| Environment | `python-dotenv` | Secure credential loading from `.env` |

---

## 📈 Performance

- **Memory Footprint:** < 90 MB RSS (SeleniumBase terminates immediately after token extraction)
- **Scrape Interval:** Every 30 seconds across all tracked targets concurrently
- **Database Cleanup:** Old job records auto-pruned after 30 days
- **Token Lifespan:** Up to 11 hours per session before refresh is required

---

## 📄 License

This project is for educational and personal use only. Scraping Upwork may violate their Terms of Service. Use responsibly.
