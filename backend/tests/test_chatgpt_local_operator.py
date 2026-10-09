"""Synthetic native controller/callback tests; no system browser or TCP listener."""

import io
from email.message import Message
from urllib.parse import parse_qs, urlsplit

import pytest

from personal_ai.llm.chatgpt.oauth import OAuthFailure
from personal_ai.local_bridge import __main__ as controller
from personal_ai.local_bridge.store import LocalStoreError
from tests.test_chatgpt_local_lifecycle import connected_lifecycle


@pytest.mark.parametrize("duplicate", [False, True])
def test_native_callback_never_returns_or_logs_auth_code_or_url(
    tmp_path, monkeypatch, caplog, duplicate
):
    lifecycle, _, _ = connected_lifecycle(tmp_path)
    observed = {}

    class SyntheticListener:
        def __init__(self, address, handler):
            assert address == ("127.0.0.1", 0)
            self.handler, self.server_port = handler, 54321
            observed["started"] = True

        def handle_request(self):
            query = parse_qs(urlsplit(observed["url"]).query)
            handler = self.handler.__new__(self.handler)
            handler.client_address = ("127.0.0.1", 1234)
            handler.headers = Message()
            handler.headers["Host"] = "127.0.0.1:54321"
            handler.path = (
                "/auth/callback?state="
                + query["state"][0]
                + ("&code=synthetic-callback-code&client_id=oaiapp_newregistration")
            )
            if duplicate:
                handler.path += "&code=other-code"
            handler.wfile = io.BytesIO()
            handler.send_response = lambda status: observed.update(status=status)
            handler.send_header = lambda key, value: None
            handler.end_headers = lambda: None
            handler.do_GET()
            observed["body"] = handler.wfile.getvalue()

        def server_close(self):
            observed["closed"] = True

    def open_system_browser(url):
        assert observed["started"]
        observed["url"] = url
        return True

    monkeypatch.setattr(controller, "HTTPServer", SyntheticListener)
    monkeypatch.setattr(controller.webbrowser, "open", open_system_browser)
    if duplicate:
        with pytest.raises(OAuthFailure):
            controller.local_sign_in(lifecycle)
    else:
        connection = controller.local_sign_in(lifecycle)
        assert connection.state == "connected"
    assert observed["closed"] and observed["status"] == 200
    assert b"synthetic-callback-code" not in observed["body"]
    assert observed["url"] not in caplog.text
    assert not lifecycle._attempts


def test_missing_configuration_has_no_live_compatibility_or_cloud_signer(tmp_path):
    lifecycle, _, _ = connected_lifecycle(tmp_path)
    issuer, keys, gates, private_network = controller.read_local_configuration(lifecycle.store)
    assert issuer == "unconfigured" and not keys and not gates and private_network is False
    config = lifecycle.store.directory / "compatibility.json"
    config.write_text('{"access_token":"do-not-echo-misconfigured-input"}')
    config.chmod(0o600)
    with pytest.raises(LocalStoreError) as captured:
        controller.read_local_configuration(lifecycle.store)
    assert "do-not-echo" not in str(captured.value)
