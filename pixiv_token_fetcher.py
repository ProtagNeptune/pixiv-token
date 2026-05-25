import base64
import hashlib
import json
import logging
import secrets
import sys
import requests
import time
import re
from pathlib import Path
from cloakbrowser import launch
from playwright.sync_api import TimeoutError

__all__ = ["PixivTokenFetcher", "DEFAULT_CACHE_DIR", "main"]

log = logging.getLogger(__name__)

PIXIV_CLIENT_ID = "MOBrBDS8blbauoSck0ZfDbtuzpyT"
PIXIV_CLIENT_SECRET = "lsACyCD94FhDUtGTXi3QzcFE2uU1hqtDaKeqrdwj"
PIXIV_TOKEN_URL = "https://oauth.secure.pixiv.net/auth/token"
REDIRECT_URI = "https://app-api.pixiv.net/web/v1/users/auth/pixiv/callback"
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
API_UA = "PixivAndroidApp/5.0.234 (Android 11; Pixel 5)"

EMAIL_SELECTORS = [
    "input[autocomplete^='username']",
    "input[placeholder*='メールアドレス']",
    "input[type='email']",
]
PASSWORD_SELECTORS = [
    "input[autocomplete^='current-password']",
    "input[placeholder*='パスワード']",
    "input[type='password']",
]
SKIP_BUTTON_TEXTS = ["Remind me later", "Skip", "あとで", "スキップ"]

DEFAULT_CACHE_DIR = Path.home() / ".pixiv-token"
EXPIRY_SAFETY_MARGIN = 60  # seconds — refresh slightly before actual expiry
TOKEN_FIELDS = ("access_token", "refresh_token", "expires_at")


def _sanitize_account(name: str) -> str:
    return re.sub(r"[^\w@.\-]", "_", name)


class PixivTokenFetcher:
    def __init__(self, username: str = None, password: str = None, headless=True,
                 cache_dir=None, account: str = None):
        self.headless = headless
        self.username = username
        self.password = password
        self.cache_dir = Path(cache_dir) if cache_dir else DEFAULT_CACHE_DIR
        self.account = account or username
        self.code_verifier = secrets.token_urlsafe(64)
        self.code_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(self.code_verifier.encode()).digest()
        ).rstrip(b'=').decode('ascii')

    def _cache_file(self, account: str) -> Path:
        return self.cache_dir / f"{_sanitize_account(account)}.json"

    def list_cached_accounts(self):
        if not self.cache_dir.is_dir():
            return []
        accounts = []
        for f in sorted(self.cache_dir.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            accounts.append({
                "username": data.get("username", f.stem),
                "expires_at": data.get("expires_at", 0),
                "path": f,
            })
        return accounts

    def _resolve_account(self) -> str:
        if self.account:
            return self.account
        cached = self.list_cached_accounts()
        if len(cached) == 1:
            return cached[0]["username"]
        if len(cached) > 1:
            names = ", ".join(a["username"] for a in cached)
            raise RuntimeError(
                f"Multiple cached accounts found ({names}). Specify --account."
            )
        return None

    def _load_cache(self, account: str):
        try:
            return json.loads(self._cache_file(account).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _save_cache(self, token_info, account: str):
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "username": account,
            "access_token": token_info["access_token"],
            "refresh_token": token_info["refresh_token"],
            "expires_at": time.time() + token_info.get("expires_in", 3600) - EXPIRY_SAFETY_MARGIN,
        }
        self._cache_file(account).write_text(json.dumps(data, indent=2), encoding="utf-8")
        return data

    def _refresh(self, refresh_token):
        resp = requests.post(PIXIV_TOKEN_URL, data={
            "client_id": PIXIV_CLIENT_ID,
            "client_secret": PIXIV_CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "include_policy": "true",
        }, headers={"User-Agent": API_UA})
        return resp.json()

    def get_token(self, force_login=False):
        account = self._resolve_account()

        if not force_login and account:
            cache = self._load_cache(account)
            if cache:
                if cache.get("expires_at", 0) > time.time():
                    log.info("using cached access token for %s", account)
                    return cache
                refresh_token = cache.get("refresh_token")
                if refresh_token:
                    log.info("refreshing access token for %s", account)
                    try:
                        token_info = self._refresh(refresh_token)
                        if "access_token" in token_info:
                            return self._save_cache(token_info, account)
                        log.warning("refresh rejected by pixiv: %s", token_info)
                    except requests.RequestException as e:
                        log.warning("refresh request failed: %s", e)

        if not self.username or not self.password:
            raise RuntimeError(
                "No valid cached token and no credentials provided. "
                "Pass --username/--password to perform browser login."
            )

        code = self.fetch_code()
        if not code:
            raise RuntimeError("Failed to capture authorization code")
        token_info = self.exchange_token(code)
        if "access_token" not in token_info:
            raise RuntimeError(f"Token exchange failed: {token_info}")
        return self._save_cache(token_info, self.username)

    def _get_login_url(self):
        return (
            "https://app-api.pixiv.net/web/v1/login?"
            f"code_challenge={self.code_challenge}&"
            "code_challenge_method=S256&client=pixiv-android"
        )

    def _slow_type(self, page, selector: str, text: str, delay: float = 0.08):
        page.focus(selector)
        for char in text:
            page.keyboard.insert_text(char)
            time.sleep(delay)

    def _find_input(self, page, selectors: list, timeout=3000):
        for selector in selectors:
            try:
                el = page.wait_for_selector(selector, timeout=timeout)
                if el and el.is_visible():
                    return selector
            except TimeoutError:
                continue
        return None

    def _perform_login(self, page):
        email_selector = self._find_input(page, EMAIL_SELECTORS)
        if not email_selector:
            log.warning("username input field not found")
            return

        self._slow_type(page, email_selector, self.username)
        log.info("filled username field")

        pwd_selector = self._find_input(page, PASSWORD_SELECTORS)
        if not pwd_selector:
            page.keyboard.press("Enter")
            time.sleep(2)
            pwd_selector = self._find_input(page, PASSWORD_SELECTORS)

        if not pwd_selector:
            log.warning("password input field not found")
            return

        self._slow_type(page, pwd_selector, self.password)
        log.info("filled password field")

        login_btn = page.locator("button:has-text('ログイン')")
        if login_btn.count() > 0:
            login_btn.first.click()
        else:
            page.keyboard.press("Enter")
        log.info("submitted login form")

    def _skip_security_prompts(self, page):
        for btn_text in SKIP_BUTTON_TEXTS:
            btn = page.locator(f"button:has-text('{btn_text}')")
            if btn.count() > 0 and btn.first.is_visible():
                log.info("skipping security prompt via %r button", btn_text)
                btn.first.click()
                time.sleep(1)
                return True
        return False

    def fetch_code(self):
        browser = launch(headless=self.headless)
        try:
            context = browser.new_context(
                user_agent=BROWSER_UA,
                viewport={"width": 1280, "height": 720},
                locale="ja-JP",
            )
            page = context.new_page()
            cdp_session = context.new_cdp_session(page)
            cdp_session.send("Network.enable")

            captured_code = None

            def on_request_will_be_sent(event):
                nonlocal captured_code
                url = event.get("request", {}).get("url", "")
                check_url = url or event.get("documentURL", "")
                if check_url.startswith("pixiv://account/login"):
                    match = re.search(r"code=([\w-]+)", check_url)
                    if match:
                        captured_code = match.group(1)
                        log.info("captured authorization code")
                        log.debug("authorization code value: %s", captured_code)
                        page.close()

            cdp_session.on("Network.requestWillBeSent", on_request_will_be_sent)

            log.info("opening pixiv login page")
            page.goto(self._get_login_url())
            self._perform_login(page)

            for _ in range(30):
                if captured_code or page.is_closed():
                    break
                try:
                    self._skip_security_prompts(page)
                except Exception:
                    log.debug("skip_security_prompts raised", exc_info=True)
                time.sleep(1)

            if not captured_code:
                log.warning("timed out waiting for authorization code")

            return captured_code
        finally:
            browser.close()

    def exchange_token(self, code):
        resp = requests.post(PIXIV_TOKEN_URL, data={
            "client_id": PIXIV_CLIENT_ID,
            "client_secret": PIXIV_CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": self.code_verifier,
            "redirect_uri": REDIRECT_URI,
            "include_policy": "true",
        }, headers={"User-Agent": API_UA})
        return resp.json()


def _build_parser():
    import argparse
    parser = argparse.ArgumentParser(description="Fetch Pixiv OAuth access/refresh token")
    parser.add_argument("--username", "-u", help="Pixiv email (only needed when cache is missing/invalid)")
    parser.add_argument("--password", "-p", help="Pixiv password (only needed when cache is missing/invalid)")
    parser.add_argument("--account", "-a", help="Select cached account by email (auto-detected if only one is cached)")
    parser.add_argument("--no-headless", action="store_true", help="Show browser window")
    parser.add_argument("--cache-dir", help=f"Token cache directory (default: {DEFAULT_CACHE_DIR})")
    parser.add_argument("--force-login", action="store_true", help="Ignore cache and perform a fresh browser login")
    parser.add_argument("--list-accounts", action="store_true", help="List cached accounts and exit")
    parser.add_argument("--json", action="store_true", help="Output the token record as a single JSON object on stdout")
    parser.add_argument("--print", dest="print_field", choices=TOKEN_FIELDS,
                        help="Print only the given field's raw value to stdout (for shell pipelines)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging on stderr")
    parser.add_argument("--quiet", "-q", action="store_true", help="Only log warnings and errors on stderr")
    return parser


CLI_LOG_FORMAT = "[%(levelname)s] %(message)s"
CLI_VERBOSE_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def _configure_cli_logging(verbose: bool, quiet: bool):
    level = logging.DEBUG if verbose else (logging.WARNING if quiet else logging.INFO)
    fmt = CLI_VERBOSE_LOG_FORMAT if verbose else CLI_LOG_FORMAT
    logging.basicConfig(level=level, format=fmt, datefmt="%Y-%m-%d %H:%M:%S",
                        stream=sys.stderr, force=True)


def main(argv=None):
    args = _build_parser().parse_args(argv)
    _configure_cli_logging(args.verbose, args.quiet)

    fetcher = PixivTokenFetcher(
        username=args.username,
        password=args.password,
        headless=not args.no_headless,
        cache_dir=args.cache_dir,
        account=args.account,
    )

    if args.list_accounts:
        rows = fetcher.list_cached_accounts()
        if args.json:
            payload = [
                {"username": r["username"], "expires_at": r["expires_at"]}
                for r in rows
            ]
            print(json.dumps(payload, indent=2))
            return 0
        if not rows:
            print("(no cached accounts)")
        else:
            now = time.time()
            print(f"{'USERNAME':<32}{'EXPIRES':<22}STATUS")
            for r in rows:
                exp = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(r['expires_at']))
                status = "valid" if r['expires_at'] > now else "expired"
                print(f"{r['username']:<32}{exp:<22}{status}")
        return 0

    try:
        token = fetcher.get_token(force_login=args.force_login)
    except RuntimeError as e:
        log.error("%s", e)
        return 1

    if args.print_field:
        print(token[args.print_field])
    elif args.json:
        print(json.dumps(token, indent=2))
    else:
        exp = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(token['expires_at']))
        print(f"access_token:  {token['access_token']}")
        print(f"refresh_token: {token['refresh_token']}")
        print(f"expires_at:    {exp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
