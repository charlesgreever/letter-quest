#!/usr/bin/env python3
"""Letter Quest — serves the game and a shared spelling-list API."""
from __future__ import annotations

import json
import os
import re
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / "public"
DATA = Path(os.environ.get("DATA_DIR", ROOT / "data"))
WORDS_JSON = DATA / "words.json"
WORDS_TXT = DATA / "words.txt"
PORT = int(os.environ.get("PORT", "8080"))
HOST = os.environ.get("HOST", "0.0.0.0")
WORD_RE = re.compile(r"^[a-z]{2,12}$")


def parse_words(text: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in re.split(r"[^A-Za-z]+", text or ""):
        w = raw.lower()
        if WORD_RE.match(w) and w not in seen:
            seen.add(w)
            out.append(w)
    return out


def load_words() -> list[str]:
    if WORDS_JSON.exists():
        try:
            data = json.loads(WORDS_JSON.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("words"), list):
                return parse_words(" ".join(str(x) for x in data["words"]))
            if isinstance(data, list):
                return parse_words(" ".join(str(x) for x in data))
        except (OSError, json.JSONDecodeError, TypeError):
            pass
    if WORDS_TXT.exists():
        try:
            return parse_words(WORDS_TXT.read_text(encoding="utf-8"))
        except OSError:
            pass
    return []


def save_words(words: list[str]) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"words": words}, indent=2) + "\n"
    WORDS_JSON.write_text(payload, encoding="utf-8")
    WORDS_TXT.write_text(("\n".join(words) + "\n") if words else "", encoding="utf-8")


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PUBLIC), **kwargs)

    def log_message(self, fmt: str, *args) -> None:
        print(f"{self.client_address[0]} {fmt % args}", flush=True)

    def end_headers(self) -> None:
        if urlparse(self.path).path.startswith("/api/"):
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    def _json(self, code: int, obj: object) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,PUT,POST,DELETE,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/health":
            self._json(200, {"ok": True, "words": len(load_words())})
            return
        if path == "/api/words":
            self._json(200, {"words": load_words()})
            return
        super().do_GET()

    def do_PUT(self) -> None:
        self._write_words()

    def do_POST(self) -> None:
        if urlparse(self.path).path == "/api/words":
            self._write_words()
            return
        self.send_error(404)

    def do_DELETE(self) -> None:
        if urlparse(self.path).path != "/api/words":
            self.send_error(404)
            return
        save_words([])
        self._json(200, {"ok": True, "words": []})

    def _write_words(self) -> None:
        if urlparse(self.path).path != "/api/words":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8", "replace")
        text = raw
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                if isinstance(data.get("words"), list):
                    text = " ".join(str(x) for x in data["words"])
                else:
                    text = str(data.get("text") or "")
            elif isinstance(data, list):
                text = " ".join(str(x) for x in data)
        except json.JSONDecodeError:
            pass
        words = parse_words(text)
        save_words(words)
        self._json(200, {"ok": True, "words": words})


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Letter Quest  http://{HOST}:{PORT}  data={DATA}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
