"""
Stub heavyweight browser dependencies before pixiv_token_fetcher is imported.

These tests cover non-browser logic (cache I/O, account resolution, token refresh
orchestration, CLI output). The real cloakbrowser / playwright packages are only
needed by fetch_code(), which is always mocked in tests.
"""
import sys
import types


def _install_stub(name, attrs=None):
    if name in sys.modules:
        return sys.modules[name]
    mod = types.ModuleType(name)
    for k, v in (attrs or {}).items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


_install_stub("cloakbrowser", {"launch": lambda **kw: None})

_playwright = _install_stub("playwright")
_sync_api = _install_stub("playwright.sync_api", {
    "TimeoutError": type("TimeoutError", (Exception,), {}),
})
_playwright.sync_api = _sync_api
