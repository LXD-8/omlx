# SPDX-License-Identifier: Apache-2.0
"""Wire contract for the macOS app's main-API-key exchange.

The menubar app POSTs the permanent main API key to trade it for a
short-lived auto-login token. Both halves of that call are hand-written
and independently free to drift: Swift builds the URL path in
``MenubarController.fetchAutoLoginToken`` and the JSON body field in the
request builder it posts, while the server
declares the route path (``@router.post("/api/auto-login-token")`` on a
router mounted at ``/admin``) and the body model (``AutoLoginTokenRequest.key``).

Nothing links them. Rename either the path or the field and the exchange
simply 404s/422s, the app falls back to opening the login page, and the
dashboard just stops auto-logging in — silently, because the fallback is
deliberate. These tests read the Swift source and the Python route/model,
so the next rename fails here instead of shipping that.

Static on purpose: no server, no macOS build, no HTTP call.
"""

import re
from pathlib import Path

from omlx.admin.routes import AutoLoginTokenRequest, router

ROOT = Path(__file__).resolve().parents[1]
MENUBAR_CONTROLLER = (
    ROOT / "apps" / "omlx-mac" / "Sources" / "Menubar" / "MenubarController.swift"
)

EXCHANGE_HELPER = "func fetchAutoLoginToken("
EXCHANGE_BUILDER = "static func autoLoginTokenRequest("
SERVER_ROUTE_PATH = "/admin/api/auto-login-token"

# The next method on the same type; the app indents its members four spaces.
NEXT_METHOD = re.compile(
    r"^    (?:@objc\s+)?(?:private\s+|internal\s+|public\s+)?func ", re.M
)
COMPS_PATH = re.compile(r'comps\.path\s*=\s*"([^"]+)"')
# `request.httpBody = try? JSONSerialization.data(withJSONObject: ["key": apiKey])`
BODY_FIELD = re.compile(
    r'JSONSerialization\.data\(withJSONObject:\s*\[\s*"([A-Za-z_][A-Za-z0-9_]*)"\s*:'
)


def _method_body(marker: str) -> str:
    """The Swift source of the member ``marker`` starts, up to the next one."""
    source = MENUBAR_CONTROLLER.read_text()
    assert marker in source, f"MenubarController no longer declares {marker}"
    start = source.index(marker)
    rest = source[start:]
    end = NEXT_METHOD.search(rest, len(marker))
    return rest if end is None else rest[: end.start()]


def _exchange_helper_body() -> str:
    """The Swift source of ``fetchAutoLoginToken`` only."""
    return _method_body(EXCHANGE_HELPER)


def _swift_exchange_path() -> str:
    match = COMPS_PATH.search(_exchange_helper_body())
    assert match, f"{EXCHANGE_HELPER}) no longer sets comps.path"
    return match.group(1)


def _swift_body_field() -> str:
    """The JSON body field, wherever the exchange assembles it.

    The body is built by the request the helper posts, which is its own member
    now that the exchange carries a timeout of its own.
    """
    for marker in (EXCHANGE_BUILDER, EXCHANGE_HELPER):
        match = BODY_FIELD.search(_method_body(marker))
        if match:
            return match.group(1)
    raise AssertionError("the app no longer posts a JSON body field")


def test_the_exchange_times_out_before_its_token_does():
    """The token lives 30 s; a server that accepts the connection and then
    never answers must not hold the menubar click for URLSession's 60 s
    default before the browser opens at all."""
    match = re.search(
        r"request\.timeoutInterval\s*=\s*([0-9.]+)",
        _method_body(EXCHANGE_BUILDER),
    )
    assert match, "the exchange sets no timeout of its own"
    assert float(match.group(1)) <= 30, "a reply slower than the token is worthless"


def _server_exchange_route():
    for route in router.routes:
        endpoint = getattr(route, "endpoint", None)
        if endpoint is not None and endpoint.__name__ == "create_auto_login_token_route":
            return route
    raise AssertionError("the server no longer declares create_auto_login_token_route")


def test_the_swift_parser_found_the_exchange_call():
    """Guards the parser itself: a renamed helper must not yield nothing."""
    body = _exchange_helper_body()
    assert "apiKey" in body
    assert _swift_exchange_path().startswith("/admin/")
    assert _swift_body_field()


def test_the_app_posts_to_the_route_the_server_declares():
    route = _server_exchange_route()
    assert "POST" in route.methods
    # The server route can move, but the app has to move with it.
    assert route.path == SERVER_ROUTE_PATH
    assert _swift_exchange_path() == route.path, (
        "MenubarController.fetchAutoLoginToken posts to "
        f"{_swift_exchange_path()!r} but the server serves {route.path!r}; the "
        "auto-login exchange would 404 and the dashboard would silently open "
        "the login page instead."
    )


def test_the_app_sends_the_field_the_server_model_declares():
    accepted = set(AutoLoginTokenRequest.model_fields)
    field = _swift_body_field()
    assert accepted == {"key"}, (
        f"AutoLoginTokenRequest now accepts {sorted(accepted)}; the Swift body "
        f"only sends {field!r}."
    )
    assert field in accepted, (
        f"MenubarController.fetchAutoLoginToken sends {field!r}, which "
        f"AutoLoginTokenRequest does not accept ({sorted(accepted)}); Pydantic "
        "would reject the request with 422."
    )
