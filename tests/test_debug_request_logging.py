# SPDX-License-Identifier: Apache-2.0
"""Tests for the trace-level request body logging middleware."""

import json

import pytest

from omlx.server import DebugRequestLoggingMiddleware, _is_textual_body

TRACE = 5


class TestIsTextualBody:
    def test_textual_types(self):
        assert _is_textual_body("application/json")
        assert _is_textual_body("application/json; charset=utf-8")
        assert _is_textual_body("application/problem+json")
        assert _is_textual_body("application/x-www-form-urlencoded")
        assert _is_textual_body("text/plain")

    def test_binary_types(self):
        assert not _is_textual_body("multipart/form-data; boundary=xyz")
        assert not _is_textual_body("audio/wav")
        assert not _is_textual_body("video/mp4")
        assert not _is_textual_body("application/octet-stream")
        assert not _is_textual_body("")


def _make_scope(content_type: str, path: str = "/v1/audio/transcriptions") -> dict:
    return {
        "type": "http",
        "method": "POST",
        "path": path,
        "headers": [
            (b"content-type", content_type.encode("latin-1")),
            (b"content-length", b"12345"),
        ],
    }


def _make_receive(body: bytes):
    messages = [{"type": "http.request", "body": body, "more_body": False}]

    async def receive():
        return messages.pop(0)

    return receive


async def _noop_send(message):
    pass


class TestDebugRequestLoggingMiddleware:
    @pytest.mark.asyncio
    async def test_binary_body_not_dumped(self, caplog):
        received = []

        async def inner_app(scope, receive, send):
            message = await receive()
            received.append(message["body"])

        binary = b"\x00\x01RIFFBINARYJUNK\xff\xfe" * 4
        middleware = DebugRequestLoggingMiddleware(inner_app)
        caplog.set_level(TRACE, logger="omlx.server")

        await middleware(
            _make_scope("multipart/form-data; boundary=xyz"),
            _make_receive(binary),
            _noop_send,
        )

        # Body reaches the app untouched (streamed, not re-buffered)
        assert received == [binary]
        logged = "\n".join(r.getMessage() for r in caplog.records)
        assert "bytes omitted" in logged
        assert "multipart/form-data" in logged
        assert "RIFFBINARYJUNK" not in logged

    @pytest.mark.asyncio
    async def test_json_body_still_logged(self, caplog):
        received = []

        async def inner_app(scope, receive, send):
            message = await receive()
            received.append(message["body"])

        body = b'{"model": "whisper", "stream": true}'
        middleware = DebugRequestLoggingMiddleware(inner_app)
        caplog.set_level(TRACE, logger="omlx.server")

        await middleware(
            _make_scope("application/json"),
            _make_receive(body),
            _noop_send,
        )

        assert received == [body]
        logged = "\n".join(r.getMessage() for r in caplog.records)
        assert '"model": "whisper"' in logged


CREDENTIAL_PATHS = ("/admin/api/login", "/admin/api/auto-login-token")
MAIN_API_KEY = "sk-main-PERMANENT-key-9f3a"


async def _log_body(caplog, path: str, body: bytes):
    """Run one POST body through the middleware.

    Returns the bytes the inner app received plus the concatenated level-5
    log text, so a test can check the route still sees the credential *and*
    the log does not.
    """
    received = []

    async def inner_app(scope, receive, send):
        message = await receive()
        received.append(message["body"])

    caplog.clear()
    caplog.set_level(TRACE, logger="omlx.server")
    middleware = DebugRequestLoggingMiddleware(inner_app)
    await middleware(
        _make_scope("application/json", path=path), _make_receive(body), _noop_send
    )
    return received, "\n".join(record.getMessage() for record in caplog.records)


class TestCredentialRequestBodyIsNotLogged:
    """A credential POST body must never be written to the trace log.

    The admin login form and the menubar app's main-key exchange both carry a
    live credential. The middleware must still hand the body to the route, so
    it has to decide *before* buffering anything — which is also what keeps
    this from consuming or reordering the request.
    """

    @pytest.mark.asyncio
    async def test_the_key_exchange_body_is_redacted_while_a_normal_body_is_not(
        self, caplog
    ):
        exchange_body = json.dumps({"key": MAIN_API_KEY}).encode()
        received, logged = await _log_body(
            caplog, "/admin/api/auto-login-token", exchange_body
        )
        # The route still gets the permanent key, byte for byte.
        assert received == [exchange_body]
        # ...but the log only records that the exchange happened.
        assert MAIN_API_KEY not in logged, logged
        assert "/admin/api/auto-login-token" in logged
        assert "credential body omitted" in logged

        # A harmless body on any other path keeps the old behaviour.
        normal_body = b'{"model": "whisper", "stream": true}'
        received, logged = await _log_body(
            caplog, "/v1/audio/transcriptions", normal_body
        )
        assert received == [normal_body]
        assert '"model": "whisper"' in logged

    @pytest.mark.asyncio
    async def test_the_login_password_is_redacted(self, caplog):
        password = "hunter2-the-admin-password"
        body = json.dumps({"api_key": password, "remember": True}).encode()
        received, logged = await _log_body(caplog, "/admin/api/login", body)

        assert received == [body]
        assert password not in logged, logged
        assert "/admin/api/login" in logged

    @pytest.mark.asyncio
    async def test_a_chunked_credential_body_reaches_the_app_unchanged(self, caplog):
        """Nothing is read from ``receive``, so chunks keep their order."""
        messages = [
            {"type": "http.request", "body": b'{"key": ', "more_body": True},
            {"type": "http.request", "body": b'"sk-main"', "more_body": True},
            {"type": "http.request", "body": b"}", "more_body": False},
        ]
        seen = []

        async def receive():
            return messages.pop(0)

        async def inner_app(scope, recv, send):
            while True:
                message = await recv()
                seen.append(message["body"])
                if not message.get("more_body", False):
                    break

        caplog.clear()
        caplog.set_level(TRACE, logger="omlx.server")
        middleware = DebugRequestLoggingMiddleware(inner_app)
        await middleware(
            _make_scope("application/json", path="/admin/api/auto-login-token"),
            receive,
            _noop_send,
        )

        assert seen == [b'{"key": ', b'"sk-main"', b"}"]
        assert "sk-main" not in "\n".join(r.getMessage() for r in caplog.records)

    def test_the_redaction_set_is_exactly_the_credential_routes(self):
        """Same list drives the body redaction and the brute-force logging."""
        from omlx.server import _ADMIN_CREDENTIAL_PATHS

        assert _ADMIN_CREDENTIAL_PATHS == frozenset(CREDENTIAL_PATHS)

    @pytest.mark.parametrize("path", CREDENTIAL_PATHS)
    def test_the_redacted_paths_are_real_post_routes(self, path):
        """A renamed route must not leave the redaction list pointing at air."""
        from omlx.admin.routes import router

        post_paths = {
            route.path
            for route in router.routes
            if "POST" in getattr(route, "methods", ())
        }
        assert path in post_paths, sorted(post_paths)
