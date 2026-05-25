import json
import time
from unittest.mock import patch

import pytest

from pixiv_token_fetcher import PixivTokenFetcher, _sanitize_account, main


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def cache_dir(tmp_path):
    return tmp_path / "cache"


@pytest.fixture
def fetcher(cache_dir):
    return PixivTokenFetcher(cache_dir=cache_dir)


@pytest.fixture
def token_response():
    """A shape-faithful response from Pixiv's token endpoint."""
    return {
        "access_token": "ACCESS",
        "refresh_token": "REFRESH",
        "expires_in": 3600,
    }


def _write_cache(fetcher, account, **overrides):
    fetcher.cache_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "username": account,
        "access_token": "ACCESS",
        "refresh_token": "REFRESH",
        "expires_at": time.time() + 3600,
    }
    data.update(overrides)
    fetcher._cache_file(account).write_text(json.dumps(data), encoding="utf-8")
    return data


# ---------------------------------------------------------------------------
# _sanitize_account
# ---------------------------------------------------------------------------

class TestSanitizeAccount:
    def test_plain_email_unchanged(self):
        assert _sanitize_account("user@example.com") == "user@example.com"

    def test_keeps_underscore_dash_dot_at(self):
        assert _sanitize_account("a_b-c.d@e") == "a_b-c.d@e"

    def test_path_separators_replaced(self):
        assert _sanitize_account("a/b\\c") == "a_b_c"

    def test_whitespace_replaced(self):
        assert _sanitize_account("foo bar") == "foo_bar"


# ---------------------------------------------------------------------------
# Cache I/O
# ---------------------------------------------------------------------------

class TestCacheIO:
    def test_save_creates_file_with_expected_fields(self, fetcher, token_response):
        data = fetcher._save_cache(token_response, "user@x.com")
        assert data["username"] == "user@x.com"
        assert data["access_token"] == "ACCESS"
        assert data["refresh_token"] == "REFRESH"
        # expires_at = now + expires_in - EXPIRY_SAFETY_MARGIN (60s)
        assert data["expires_at"] == pytest.approx(time.time() + 3600 - 60, abs=5)

    def test_save_then_load_roundtrip(self, fetcher, token_response):
        saved = fetcher._save_cache(token_response, "user@x.com")
        loaded = fetcher._load_cache("user@x.com")
        assert loaded == saved

    def test_load_missing_returns_none(self, fetcher):
        assert fetcher._load_cache("nobody@x.com") is None

    def test_load_corrupt_returns_none(self, fetcher):
        path = fetcher._cache_file("bad@x.com")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not-json{{", encoding="utf-8")
        assert fetcher._load_cache("bad@x.com") is None

    def test_save_sanitizes_filename(self, fetcher, token_response):
        fetcher._save_cache(token_response, "weird/name")
        files = list(fetcher.cache_dir.glob("*.json"))
        assert len(files) == 1
        assert "/" not in files[0].name


class TestListCachedAccounts:
    def test_empty_when_dir_missing(self, fetcher):
        assert fetcher.list_cached_accounts() == []

    def test_returns_all_valid_entries(self, fetcher, token_response):
        fetcher._save_cache(token_response, "a@x.com")
        fetcher._save_cache(token_response, "b@x.com")
        names = sorted(r["username"] for r in fetcher.list_cached_accounts())
        assert names == ["a@x.com", "b@x.com"]

    def test_skips_corrupt_files(self, fetcher, token_response):
        fetcher._save_cache(token_response, "good@x.com")
        (fetcher.cache_dir / "bad.json").write_text("not-json{{", encoding="utf-8")
        rows = fetcher.list_cached_accounts()
        assert [r["username"] for r in rows] == ["good@x.com"]


# ---------------------------------------------------------------------------
# _resolve_account dispatch
# ---------------------------------------------------------------------------

class TestResolveAccount:
    def test_explicit_account_wins_over_cache(self, cache_dir, token_response):
        seeder = PixivTokenFetcher(cache_dir=cache_dir)
        seeder._save_cache(token_response, "cached@x.com")
        f = PixivTokenFetcher(cache_dir=cache_dir, account="explicit@x.com")
        assert f._resolve_account() == "explicit@x.com"

    def test_username_becomes_account_when_no_explicit_account(self, cache_dir):
        f = PixivTokenFetcher(cache_dir=cache_dir, username="user@x.com")
        assert f._resolve_account() == "user@x.com"

    def test_single_cached_account_auto_selected(self, cache_dir, token_response):
        seeder = PixivTokenFetcher(cache_dir=cache_dir)
        seeder._save_cache(token_response, "only@x.com")
        f = PixivTokenFetcher(cache_dir=cache_dir)
        assert f._resolve_account() == "only@x.com"

    def test_multiple_cached_accounts_require_explicit_choice(self, cache_dir, token_response):
        seeder = PixivTokenFetcher(cache_dir=cache_dir)
        seeder._save_cache(token_response, "a@x.com")
        seeder._save_cache(token_response, "b@x.com")
        f = PixivTokenFetcher(cache_dir=cache_dir)
        with pytest.raises(RuntimeError, match="Multiple cached accounts"):
            f._resolve_account()

    def test_no_cache_no_account_returns_none(self, cache_dir):
        f = PixivTokenFetcher(cache_dir=cache_dir)
        assert f._resolve_account() is None


# ---------------------------------------------------------------------------
# get_token orchestration
# ---------------------------------------------------------------------------

class TestGetTokenOrchestration:
    def test_returns_valid_cache_without_network(self, fetcher, token_response):
        fetcher.account = "user@x.com"
        saved = fetcher._save_cache(token_response, "user@x.com")
        with patch.object(fetcher, "_refresh") as refresh, \
             patch.object(fetcher, "fetch_code") as fetch:
            result = fetcher.get_token()
        assert result == saved
        refresh.assert_not_called()
        fetch.assert_not_called()

    def test_refreshes_when_expired(self, fetcher):
        fetcher.account = "user@x.com"
        _write_cache(fetcher, "user@x.com",
                     access_token="OLD", refresh_token="REFRESH",
                     expires_at=time.time() - 100)

        new_resp = {"access_token": "NEW", "refresh_token": "REFRESH2", "expires_in": 3600}
        with patch.object(fetcher, "_refresh", return_value=new_resp) as refresh, \
             patch.object(fetcher, "fetch_code") as fetch:
            result = fetcher.get_token()

        refresh.assert_called_once_with("REFRESH")
        fetch.assert_not_called()
        assert result["access_token"] == "NEW"
        assert result["refresh_token"] == "REFRESH2"
        # Persisted to disk
        assert fetcher._load_cache("user@x.com")["access_token"] == "NEW"

    def test_browser_fallback_when_refresh_rejected(self, fetcher):
        fetcher.account = "user@x.com"
        fetcher.username = "user@x.com"
        fetcher.password = "pwd"
        _write_cache(fetcher, "user@x.com",
                     refresh_token="BAD", expires_at=time.time() - 100)

        login_resp = {"access_token": "FRESH", "refresh_token": "FRESH_R", "expires_in": 3600}
        with patch.object(fetcher, "_refresh", return_value={"error": "invalid_grant"}), \
             patch.object(fetcher, "fetch_code", return_value="CODE") as fetch, \
             patch.object(fetcher, "exchange_token", return_value=login_resp):
            result = fetcher.get_token()

        fetch.assert_called_once()
        assert result["access_token"] == "FRESH"

    def test_browser_fallback_when_refresh_network_error(self, fetcher):
        import requests as _requests
        fetcher.account = "user@x.com"
        fetcher.username = "user@x.com"
        fetcher.password = "pwd"
        _write_cache(fetcher, "user@x.com", expires_at=time.time() - 100)

        login_resp = {"access_token": "FRESH", "refresh_token": "FRESH_R", "expires_in": 3600}
        with patch.object(fetcher, "_refresh", side_effect=_requests.ConnectionError("boom")), \
             patch.object(fetcher, "fetch_code", return_value="CODE"), \
             patch.object(fetcher, "exchange_token", return_value=login_resp):
            result = fetcher.get_token()
        assert result["access_token"] == "FRESH"

    def test_no_cache_no_credentials_raises(self, fetcher):
        with pytest.raises(RuntimeError, match="No valid cached token"):
            fetcher.get_token()

    def test_force_login_bypasses_valid_cache(self, fetcher, token_response):
        fetcher.account = "user@x.com"
        fetcher.username = "user@x.com"
        fetcher.password = "pwd"
        fetcher._save_cache(token_response, "user@x.com")

        login_resp = {"access_token": "NEW", "refresh_token": "NEW_R", "expires_in": 3600}
        with patch.object(fetcher, "_refresh") as refresh, \
             patch.object(fetcher, "fetch_code", return_value="CODE") as fetch, \
             patch.object(fetcher, "exchange_token", return_value=login_resp):
            result = fetcher.get_token(force_login=True)

        refresh.assert_not_called()
        fetch.assert_called_once()
        assert result["access_token"] == "NEW"

    def test_fetch_code_failure_raises(self, fetcher):
        fetcher.username = "user@x.com"
        fetcher.password = "pwd"
        with patch.object(fetcher, "fetch_code", return_value=None):
            with pytest.raises(RuntimeError, match="capture authorization code"):
                fetcher.get_token()

    def test_exchange_failure_raises(self, fetcher):
        fetcher.username = "user@x.com"
        fetcher.password = "pwd"
        with patch.object(fetcher, "fetch_code", return_value="CODE"), \
             patch.object(fetcher, "exchange_token", return_value={"error": "bad"}):
            with pytest.raises(RuntimeError, match="Token exchange failed"):
                fetcher.get_token()


# ---------------------------------------------------------------------------
# CLI / main
# ---------------------------------------------------------------------------

class TestCLI:
    def _seed_cache(self, cache_dir, account="u@x.com",
                    access_token="ACCESS", refresh_token="REFRESH", expires_in=3600):
        f = PixivTokenFetcher(cache_dir=cache_dir)
        f._save_cache({
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_in": expires_in,
        }, account)

    def test_list_accounts_empty(self, cache_dir, capsys):
        rc = main(["--cache-dir", str(cache_dir), "--list-accounts"])
        assert rc == 0
        assert "no cached accounts" in capsys.readouterr().out

    def test_list_accounts_json(self, cache_dir, capsys):
        self._seed_cache(cache_dir)
        rc = main(["--cache-dir", str(cache_dir), "--list-accounts", "--json"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert len(data) == 1
        assert data[0]["username"] == "u@x.com"
        assert "expires_at" in data[0]

    def test_print_field_outputs_raw_value(self, cache_dir, capsys):
        self._seed_cache(cache_dir, access_token="THE_TOKEN")
        rc = main(["--cache-dir", str(cache_dir), "--print", "access_token"])
        assert rc == 0
        assert capsys.readouterr().out.strip() == "THE_TOKEN"

    def test_json_output_has_all_fields(self, cache_dir, capsys):
        self._seed_cache(cache_dir, access_token="A", refresh_token="R")
        rc = main(["--cache-dir", str(cache_dir), "--json"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["access_token"] == "A"
        assert data["refresh_token"] == "R"
        assert data["username"] == "u@x.com"
        assert "expires_at" in data

    def test_default_output_format(self, cache_dir, capsys):
        self._seed_cache(cache_dir, access_token="A", refresh_token="R")
        rc = main(["--cache-dir", str(cache_dir)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "access_token:  A" in out
        assert "refresh_token: R" in out
        assert "expires_at:" in out

    def test_no_cache_no_credentials_returns_error_code(self, cache_dir):
        rc = main(["--cache-dir", str(cache_dir)])
        assert rc == 1

    def test_logs_to_stderr_not_stdout(self, cache_dir, capsys):
        self._seed_cache(cache_dir)
        main(["--cache-dir", str(cache_dir), "--print", "access_token"])
        captured = capsys.readouterr()
        # stdout: just the raw token, no log decoration
        assert "[INFO]" not in captured.out
        # stderr: contains the info log
        assert "[INFO]" in captured.err
        assert "using cached access token" in captured.err

    def test_quiet_suppresses_info_logs(self, cache_dir, capsys):
        self._seed_cache(cache_dir)
        main(["--cache-dir", str(cache_dir), "--quiet", "--print", "access_token"])
        assert "[INFO]" not in capsys.readouterr().err
