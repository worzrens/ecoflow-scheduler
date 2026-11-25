"""Tiny local listener (127.0.0.1 only) that receives the DTEK schedule from the user's own browser.

The site blocks automated requests, but a real browser that passed its check can hand the page's schedule over:
the bookmarklet in Settings POSTs `DisconSchedule.fact` to http://127.0.0.1:<port>/schedule.
"""
from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

MAX_BODY = 4_000_000


def start(port: int, handle: Callable[[str], str],
          files: dict[str, str] | None = None) -> ThreadingHTTPServer | None:
    """`handle(text)` returns the reply text (raises OSError/ValueError with a readable message on bad input).
    `files` {path: javascript text} are served on GET (the userscript to install in the browser).
    Returns None when the port is taken (a second instance); the first one keeps listening."""

    class H(BaseHTTPRequestHandler):
        def _send(self, code: int, text: str, kind: str = "text/plain"):
            body = text.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", f"{kind}; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "*")
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self):
            self._send(204, "")

        def do_GET(self):
            script = (files or {}).get(self.path.split("?")[0])
            if script is not None:
                return self._send(200, script, "text/javascript")
            self._send(200, "EcoFlow Scheduler is listening")

        def do_POST(self):
            if self.path.split("?")[0] != "/schedule":
                return self._send(404, "Unknown path")
            try:
                n = int(self.headers.get("Content-Length") or 0)
                if not 0 < n <= MAX_BODY:
                    return self._send(413, "Empty or too large")
                self._send(200, handle(self.rfile.read(n).decode("utf-8", "replace")))
            except (OSError, ValueError) as e:
                self._send(400, str(e))

        def log_message(self, *args):
            pass

    try:
        srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    except OSError:
        return None
    threading.Thread(target=srv.serve_forever, daemon=True, name="ecoflow-import").start()
    return srv
