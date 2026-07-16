"""Local HTTP server for the Sutura viewer app.

Zero third-party deps (stdlib http.server). Serves the static single-page app and
a small read-only JSON API over the result store:

    GET  /                      -> the app
    GET  /api/runs              -> [{job_id, created, status, methods, ...}]
    GET  /api/runs/<job_id>     -> full bundle (metadata, metrics, routing, qc,
                                   reconstruction, report_md)
    POST /api/chat  {job_id, question}  -> grounded answer about that run

Everything is local; the server never runs alignment.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from . import __version__, chat, store

STATIC = Path(__file__).parent / "static"
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("application/wasm", ".wasm")


class Handler(BaseHTTPRequestHandler):
    server_version = f"SuturaViewer/{__version__}"

    # --- helpers ------------------------------------------------------- #
    def _send_json(self, obj, status=200):
        body = json.dumps(obj, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path):
        if not path.is_file():
            self._send_json({"error": "not found"}, 404)
            return
        ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _static(self, rel: str):
        # resolve safely under STATIC (no path traversal)
        target = (STATIC / rel.lstrip("/")).resolve()
        if not str(target).startswith(str(STATIC.resolve())):
            self._send_json({"error": "forbidden"}, 403)
            return
        self._send_file(target)

    def log_message(self, *args):
        pass   # quiet

    # --- routing ------------------------------------------------------- #
    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        if path in ("/", "/index.html"):
            self._send_file(STATIC / "index.html")
        elif path == "/api/runs":
            self._send_json({"runs": store.list_runs(),
                             "store": str(store.results_dir())})
        elif path.startswith("/api/runs/"):
            job_id = path[len("/api/runs/"):]
            run = store.load_run(job_id)
            if run is None:
                self._send_json({"error": f"run {job_id} not found"}, 404)
            else:
                self._send_json(run)
        else:
            self._static(path)

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            self._send_json({"error": "bad json"}, 400)
            return
        if path == "/api/chat":
            run = store.load_run(body.get("job_id", ""))
            if run is None:
                self._send_json({"error": "run not found"}, 404)
                return
            self._send_json(chat.answer(run, body.get("question", "")))
        else:
            self._send_json({"error": "not found"}, 404)


def serve(host="127.0.0.1", port=8787, open_browser=True):
    try:                                    # UTF-8 console where possible
        import sys
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    httpd = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{port}/"
    print(f"Sutura viewer v{__version__}  ->  {url}")
    print(f"reading bundles from {store.results_dir()}")
    print("display-only; the CLI produces the bundles. Ctrl-C to stop.")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        httpd.server_close()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="sutura-app",
                                description="Local Sutura result viewer (display-only).")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8787)
    p.add_argument("--no-browser", action="store_true")
    p.add_argument("--version", action="version", version=f"sutura-app {__version__}")
    args = p.parse_args(argv)
    serve(args.host, args.port, open_browser=not args.no_browser)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
