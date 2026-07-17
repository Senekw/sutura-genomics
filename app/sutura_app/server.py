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
import os
import queue
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from . import __version__, chat, store
from .live import LiveHub, run_live

STATIC = Path(__file__).parent / "static"
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("application/wasm", ".wasm")

HUB = LiveHub()          # shared live-progress event bus


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

    # --- server-sent events for the live view -------------------------- #
    def _sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        q = HUB.subscribe()
        try:
            while True:
                try:
                    msg = q.get(timeout=15)
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    continue
                payload = json.dumps(msg, default=str)
                self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            HUB.unsubscribe(q)

    # --- routing ------------------------------------------------------- #
    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        if path in ("/", "/index.html"):
            self._send_file(STATIC / "index.html")
        elif path == "/live":
            self._send_file(STATIC / "live.html")
        elif path == "/api/live/stream":
            self._sse()
        elif path == "/api/live/state":
            self._send_json({"running": HUB.running,
                             "history_len": len(HUB.history)})
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


def serve_live(instruction: str, host="127.0.0.1", port=8787,
               open_browser=True) -> int:
    """Run a REAL alignment and stream it live to the browser AND the terminal,
    then keep serving so the finished 3D view stays interactive.

    The pipeline runs under a watchdog (see live.run_live): the terminal shows
    the same stage-by-stage progress as the browser, a heartbeat proves both are
    alive on long stages, and a stalled stage surfaces an error instead of
    hanging silently."""
    try:
        import sys
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    if not instruction:
        print("usage: sutura-app live \"align ./data and reconstruct in 3D\"")
        return 2
    # Keep the live browser view responsive: a full-resolution PASTE2 pair takes
    # ~6-7 min, so in live mode cap per-pair time and skip a pair that exceeds it
    # (with an honest note) rather than stalling the animation. Headless/batch
    # runs leave this OFF and let PASTE2 finish. User-set value always wins.
    os.environ.setdefault("SUTURA_ALIGN_TIMEOUT", "180")
    httpd = ThreadingHTTPServer((host, port), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://{host}:{port}/live"

    # Terminal renderer: tee the SAME event stream the browser gets to the
    # console, so `--live` no longer looks frozen while work is happening.
    from sutura_cli.render import ConsoleSink, banner
    console_sink = ConsoleSink()
    banner(console_sink.console, "live · streaming to the browser · no data egress")
    console_sink.console.print(f"[#d9c4ff]▸[/#d9c4ff] live view: {url}")
    console_sink.console.print(f"[grey58]▸[/grey58] [italic]{instruction}[/italic]\n")

    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    time.sleep(1.0)                       # let the browser connect first

    from sutura_cli.core.config import Config

    def _status(line: str):
        console_sink.console.print(f"[grey58]{line}[/grey58]")

    outcome = run_live(instruction, Config.load(), HUB,
                       extra_sinks=[console_sink], on_status=_status)

    status = outcome.get("status")
    if status == "complete":
        console_sink.console.print(
            f"\n[green]✓ alignment complete[/green] — view at {url}  "
            f"(Ctrl-C to stop)")
    else:
        console_sink.console.print(
            f"\n[red]✗ live run did not finish cleanly ({status})[/red]: "
            f"{outcome.get('error') or 'see above'}\n"
            f"the viewer is still up at {url}  (Ctrl-C to stop)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        httpd.server_close()
    return 0 if status == "complete" else 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="sutura-app",
        description="Local Sutura viewer + live alignment view (display-only).")
    p.add_argument("cmd", nargs="*",
                   help='"live \"<instruction>\"" to run + watch a live '
                        "alignment; omit to open the result viewer")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8787)
    p.add_argument("--no-browser", action="store_true")
    p.add_argument("--version", action="version", version=f"sutura-app {__version__}")
    args = p.parse_args(argv)
    if args.cmd and args.cmd[0] == "live":
        instruction = " ".join(args.cmd[1:]).strip()
        return serve_live(instruction, args.host, args.port,
                          open_browser=not args.no_browser)
    serve(args.host, args.port, open_browser=not args.no_browser)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
