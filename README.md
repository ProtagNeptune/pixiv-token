# Pixiv OAuth Token Fetcher

🌍 [English](README.md) | [简体中文](README.zh-CN.md)

A Python automation tool that simulates Pixiv OAuth login, captures the authorization code, and exchanges it for an access token.

---

## 📦 Features

- ✅ Automated Pixiv login (username/password)
- ✅ Headless mode support
- ✅ Visible (non-headless) mode support
- ✅ Console-based authorization code capture via CDP
- ✅ Access token & refresh token retrieval
- ✅ Slow typing to bypass bot detection
- ✅ Auto-skip security prompt pages (Passkeys / 2FA reminders)
- ✅ Multi-selector fallback for Pixiv login form compatibility
- ✅ Token cache + auto refresh (browser login only on first run / when refresh token expires)
- ✅ Multi-account support (one cache file per email under `~/.pixiv-token/`)
- ✅ Machine-readable output (`--json`, `--print <field>`) — result on stdout, logs on stderr
- ✅ Standard `logging` integration — library is silent by default; consumers configure their own handlers
- ✅ Installable as a library (`pip install .`) and CLI (`pixiv-token`)

---

## 🚀 Installation

### 1. Clone the repository

```bash
git clone https://github.com/piglig/pixiv-token.git
cd pixiv-token
```

### 2. Install dependencies

Recommended Python version: `>=3.8`

```bash
# As a dev checkout
pip install -r requirements.txt

# Or install as a package (exposes the `pixiv-token` CLI)
pip install .
```

---

## ⚙️ Usage

### Command line

```bash
# First run for an account — credentials required, browser login performed and token cached
python pixiv_token_fetcher.py -u "your_email" -p "your_password"

# Subsequent runs — cache is used; if expired, refresh_token is used automatically
# (auto-selected when only one account is cached)
python pixiv_token_fetcher.py

# Multiple accounts — select which cached account to use
python pixiv_token_fetcher.py --account "your_email"

# List all cached accounts and their expiry
python pixiv_token_fetcher.py --list-accounts

# Visible browser mode (when login is needed)
python pixiv_token_fetcher.py -u "your_email" -p "your_password" --no-headless

# Force a fresh browser login (ignore cache)
python pixiv_token_fetcher.py -u "your_email" -p "your_password" --force-login

# Custom cache directory
python pixiv_token_fetcher.py --cache-dir ./tokens

# Machine-readable: full record as JSON on stdout (status logs go to stderr)
python pixiv_token_fetcher.py --json

# Pipeline-friendly: print a single field only (no labels, no emoji)
ACCESS_TOKEN=$(python pixiv_token_fetcher.py --print access_token)
REFRESH=$(python pixiv_token_fetcher.py --print refresh_token)

# Verbosity (logs are written to stderr only)
python pixiv_token_fetcher.py --verbose   # debug-level logs
python pixiv_token_fetcher.py --quiet     # warnings/errors only

# If installed via `pip install .`, the same CLI is available as `pixiv-token`
pixiv-token --print access_token
```

Default cache directory: `~/.pixiv-token/`, one file per account (`<email>.json`). Each file stores `username`, `access_token`, `refresh_token`, and `expires_at` — treat the directory like a credential store.

### As a module

```python
from pixiv_token_fetcher import PixivTokenFetcher

# First login for an account — credentials required
fetcher = PixivTokenFetcher(
    username="your_pixiv_email",
    password="your_pixiv_password",
    headless=True,
)
token = fetcher.get_token()  # cache → refresh → browser login (in that order)
print(token["access_token"])

# Later, reuse the cache without credentials
fetcher = PixivTokenFetcher(account="your_pixiv_email")
token = fetcher.get_token()

# List cached accounts
for acc in PixivTokenFetcher().list_cached_accounts():
    print(acc["username"], acc["expires_at"])
```

The returned `token` dict always contains `username`, `access_token`, `refresh_token`, and `expires_at` (unix seconds).

Logging: the library uses the standard `logging` module under the logger name `pixiv_token_fetcher` and ships **no handlers** by default (silent on import). Wire it into your own setup:

```python
import logging
logging.getLogger("pixiv_token_fetcher").setLevel(logging.INFO)
logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s")
```

---

## 🔧 How It Works

1. **Cache Lookup** — Resolves the account (explicit `--account`/`--username`, or auto-detected if only one is cached) and reads `~/.pixiv-token/<email>.json`; if `access_token` is still valid, returns it immediately
2. **Refresh** — If the access token has expired, calls Pixiv's `grant_type=refresh_token` endpoint and updates the cache (no browser involved)
3. **PKCE Generation** *(fallback)* — Generates `code_verifier` and `code_challenge` for OAuth PKCE flow
4. **Browser Launch** — Launches a stealth Chromium build to perform the login
5. **Auto Login** — Fills in email/password with slow typing to mimic human input
6. **Code Capture** — Intercepts the `pixiv://account/login?code=...` redirect via CDP (`Network.requestWillBeSent`)
7. **Security Prompt Handling** — Automatically clicks "Remind me later" / "Skip" if Pixiv shows a Passkeys/2FA setup page
8. **Token Exchange** — Exchanges the authorization code for access & refresh tokens and writes them to the cache

---

## 📌 Notes

- ⚠️ Do not hardcode credentials in production environments. Use environment variables or a secrets manager.
- ❌ This is not an official Pixiv SDK. Changes to Pixiv's login page may affect functionality.
- 🛡 Please comply with Pixiv's Terms of Service.
- 🔁 The refresh token is long-lived. You typically only need to run this tool once.

---

## 🧪 Example Output

```
[INFO] opening pixiv login page
[INFO] filled username field
[INFO] filled password field
[INFO] submitted login form
[INFO] skipping security prompt via 'Remind me later' button
[INFO] captured authorization code
access_token:  xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
refresh_token: xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
expires_at:    2026-05-25 14:32:10
```

The `[INFO]` lines are logs (written to stderr); `access_token` / `refresh_token` / `expires_at` are the result (written to stdout). Pipe-friendly.

---

## 🧪 Testing

Unit tests cover the non-browser logic (cache I/O, account resolution, token-refresh orchestration, CLI output contracts). Browser flow is mocked, so the suite runs in under a second without needing CloakBrowser/Playwright installed.

```bash
pip install -e ".[test]"
pytest
```

## 📝 License

See the [LICENSE](LICENSE) file for license rights and limitations (MIT).

---

## 🙋‍♀️ Contribution & Issues

Pull Requests and Issues are welcome!

---

## 📫 Contact

- GitHub: [piglig](https://github.com/piglig)
- Email: zhu1197437384@gmail.com
