"""POSIX local operator surface. No auth URL/token goes through browser IPC."""

from __future__ import annotations

import argparse
import json
import threading
import time
import webbrowser
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit
from uuid import UUID

import uvicorn
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from personal_ai.auth.dispatch_grants import DispatchGrantVerifier
from personal_ai.llm.chatgpt.oauth import OAuthFailure, OpenAIOAuth
from personal_ai.llm.chatgpt.responses import ChatGPTResponses
from personal_ai.local_bridge.http import create_loopback_app, strict_json
from personal_ai.local_bridge.lifecycle import CredentialLifecycle
from personal_ai.local_bridge.runtime import BridgeDenied, CompatibilityGate, LocalChatGPTBridge
from personal_ai.local_bridge.store import LocalStoreError, ProtectedLocalStore


def local_sign_in(lifecycle: CredentialLifecycle, *, connection_id=None):
    """Ephemeral OAuth callback listener, separate from paired browser execution."""
    outcome = {}
    attempt_id = None

    class Callback(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # BaseHTTPRequestHandler otherwise logs the authorization code URL.

        def do_GET(self):
            parsed = urlsplit(self.path)
            expected_host = f"127.0.0.1:{server.server_port}"
            if (
                self.client_address[0] != "127.0.0.1"
                or self.headers.get_all("Host") != [expected_host]
                or parsed.path != "/auth/callback"
                or len(self.path) > 16384
                or self.headers.get("Origin")
            ):
                self.send_error(403)
                return
            try:
                pairs = parse_qsl(parsed.query, keep_blank_values=True, max_num_fields=16)
                values = dict(pairs)
                if len(pairs) != len(values):
                    raise OAuthFailure("oauth_callback_invalid")
                outcome["connection"] = lifecycle.complete(attempt_id, values)
                message = b"Sign-in finished. Return to the local bridge."
            except (OAuthFailure, LocalStoreError, ValueError):
                outcome["failed"] = True
                message = b"Sign-in failed. Return to the local bridge to try again."
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'none'")
            self.send_header("Content-Length", str(len(message)))
            self.end_headers()
            self.wfile.write(message)

    # Bind before generating/opening the authorization URL. Only this port can vary.
    class BoundedCallbackServer(HTTPServer):
        def get_request(self):
            socket, address = super().get_request()
            socket.settimeout(5)
            return socket, address

    server = BoundedCallbackServer(("127.0.0.1", 0), Callback)
    server.timeout = 1
    try:
        attempt_id, url = lifecycle.begin(
            f"http://127.0.0.1:{server.server_port}/auth/callback",
            connection_id=connection_id,
        )
        if not webbrowser.open(url):
            raise OAuthFailure("oauth_system_browser_unavailable")
        deadline = time.monotonic() + 180
        while not outcome and time.monotonic() < deadline:
            server.handle_request()
        if "connection" not in outcome:
            raise OAuthFailure("oauth_sign_in_failed")
        return outcome["connection"]
    finally:
        if attempt_id is not None:
            lifecycle.cancel(attempt_id)
        server.server_close()


def read_local_configuration(store):
    path = store.directory / "compatibility.json"
    if not path.exists():
        return "unconfigured", {}, (), False
    store._check(path)
    if path.stat().st_size > 131072:
        raise LocalStoreError("bridge_configuration_invalid")
    try:
        config = strict_json(path.read_bytes())
        if set(config) != {"issuer", "keys", "gates", "private_network_verified"}:
            raise ValueError()
        if not isinstance(config["issuer"], str) or not 1 <= len(config["issuer"]) <= 200:
            raise ValueError()
        if not isinstance(config["keys"], dict) or not 1 <= len(config["keys"]) <= 8:
            raise ValueError()
        keys = {
            key_id: Ed25519PublicKey.from_public_bytes(bytes.fromhex(key))
            for key_id, key in config["keys"].items()
        }
        gates = tuple(CompatibilityGate.model_validate(value) for value in config["gates"])
        if type(config["private_network_verified"]) is not bool:
            raise ValueError()
        return config["issuer"], keys, gates, config["private_network_verified"]
    except (ValueError, TypeError, KeyError, RecursionError):
        raise LocalStoreError("bridge_configuration_invalid") from None


def main():
    parser = argparse.ArgumentParser(description="User-local ChatGPT execution bridge (gated)")
    parser.add_argument(
        "--directory", type=Path, default=Path.home() / ".local/state/personal-ai-bridge"
    )
    parser.add_argument(
        "--origin",
        action="append",
        required=True,
        help="Exact approved caller origin; repeat for each origin",
    )
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    store = ProtectedLocalStore(args.directory)
    lifecycle = CredentialLifecycle(store, OpenAIOAuth())
    with store.transaction() as tx:
        audience = UUID(tx.state.runtime_id)
    issuer, keys, gates, private_network = read_local_configuration(store)
    bridge = LocalChatGPTBridge(
        lifecycle,
        ChatGPTResponses(),
        DispatchGrantVerifier(issuer=issuer, keys=keys, audience=audience),
        origins=tuple(args.origin),
        gates=gates,
    )
    server = uvicorn.Server(
        uvicorn.Config(
            create_loopback_app(bridge, port=args.port, private_network_verified=private_network),
            host="127.0.0.1",
            port=args.port,
            proxy_headers=False,
            access_log=False,
            log_level="warning",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    print("Local bridge. Live execution requires verified local gates and a signed package.")
    print("Commands: sign-in | reauth CONNECTION | sign-out CONNECTION | status |")
    print("pair EXACT_ORIGIN CONNECTION | quit")
    try:
        while True:
            command = input("bridge> ").split()
            if not command:
                continue
            try:
                if command == ["quit"]:
                    break
                if command == ["status"]:
                    print(json.dumps([asdict(c) for c in lifecycle.connections()]))
                elif command == ["sign-in"]:
                    print(json.dumps(asdict(local_sign_in(lifecycle))))
                elif len(command) == 2 and command[0] == "reauth":
                    print(json.dumps(asdict(local_sign_in(lifecycle, connection_id=command[1]))))
                elif len(command) == 2 and command[0] == "sign-out":
                    print(json.dumps(asdict(lifecycle.disconnect(command[1]))))
                elif len(command) == 3 and command[0] == "pair":
                    session = bridge.approve_pairing(command[1], command[2])
                    # Short-lived caller capability, never an OpenAI credential.
                    print(
                        json.dumps(
                            {
                                "caller_id": str(session.caller_id),
                                "audience": str(audience),
                                "connection_id": str(session.connection_id),
                                "connection_revision": session.connection_revision,
                                "expires_at": session.expires_at,
                                "caller_authorization": session.authorization,
                            }
                        )
                    )
                else:
                    print("Unknown command.")
            except (BridgeDenied, OAuthFailure, LocalStoreError) as error:
                print(error.code)
    except (EOFError, KeyboardInterrupt):
        pass
    finally:
        server.should_exit = True
        thread.join(timeout=5)


if __name__ == "__main__":
    main()
