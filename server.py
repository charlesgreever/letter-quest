#!/usr/bin/env python3
"""Letter Quest — serves the game and a shared spelling-list API."""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / "public"
DATA = Path(os.environ.get("DATA_DIR", ROOT / "data"))
WORDS_JSON = DATA / "words.json"
WORDS_TXT = DATA / "words.txt"
LESSONS_OVERLAY = DATA / "lessons.json"
BUNDLED_CATALOG = PUBLIC / "catalog.json"
PORT = int(os.environ.get("PORT", "8080"))
HOST = os.environ.get("HOST", "0.0.0.0")
WORD_RE = re.compile(r"^[a-z]{2,12}$")
SAY_SAFE = re.compile(r"[^A-Za-z0-9 .,!?'\-]")
ESPEAK = shutil.which("espeak-ng") or shutil.which("espeak")
BODY_LIMIT = 65536
PIN = os.environ.get("LETTER_QUEST_PIN", "").strip()
VOICES = {
    "teacher": {"id": "teacher", "label": "Teacher", "espeak": "en+f3"},
    "annie": {"id": "annie", "label": "Annie", "espeak": "en-us+Annie"},
    "alicia": {"id": "alicia", "label": "Alicia", "espeak": "en-us+Alicia"},
    "andrea": {"id": "andrea", "label": "Andrea", "espeak": "en-us+Andrea"},
    "andy": {"id": "andy", "label": "Andy", "espeak": "en-us+Andy"},
    "david": {"id": "david", "label": "David", "espeak": "en-us+David"},
}
VOICE_ORDER = ["teacher", "annie", "alicia", "andrea", "andy", "david"]


def resolve_voice(name: str | None) -> str:
    key = re.sub(r"[^a-z0-9]", "", (name or "").lower())
    return VOICES.get(key, VOICES["teacher"])["espeak"]


def list_voices() -> list[dict]:
    return [{"id": VOICES[k]["id"], "label": VOICES[k]["label"]} for k in VOICE_ORDER]


class DataError(Exception):
    """On-disk data is present but unreadable. Do not invent an empty list."""


def can_write(ip: str, pin: str = "", provided: str | None = None) -> bool:
    pin = (pin or "").strip()
    if pin:
        return provided == pin
    return _is_lan(ip)


def _is_lan(ip: str) -> bool:
    if not ip:
        return False
    if ip.startswith("::ffff:"):
        ip = ip[7:]
    if ip in {"127.0.0.1", "::1", "localhost"}:
        return True
    parts = ip.split(".")
    if len(parts) != 4:
        return False
    try:
        a, b = int(parts[0]), int(parts[1])
    except ValueError:
        return False
    return a == 127 or a == 10 or (a == 192 and b == 168) or (a == 172 and 16 <= b <= 31)


def speak_wav(text: str, voice: str | None = None) -> bytes | None:
    if not ESPEAK:
        return None
    cleaned = SAY_SAFE.sub("", text or "").strip()[:180]
    if not cleaned:
        return None
    fd, path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        proc = subprocess.run(
            [ESPEAK, "-w", path, "-s", "120", "-a", "180", "-v", resolve_voice(voice), cleaned],
            capture_output=True,
            timeout=8,
            check=False,
        )
        if proc.returncode != 0:
            return None
        data = Path(path).read_bytes()
        return data if len(data) > 44 else None
    except (OSError, subprocess.TimeoutExpired):
        return None
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


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
        except (OSError, json.JSONDecodeError) as exc:
            raise DataError("words.json is not valid") from exc
        if isinstance(data, dict) and isinstance(data.get("words"), list):
            return parse_words(" ".join(str(x) for x in data["words"]))
        if isinstance(data, list):
            return parse_words(" ".join(str(x) for x in data))
        raise DataError("words.json is not a word list")
    if WORDS_TXT.exists():
        try:
            return parse_words(WORDS_TXT.read_text(encoding="utf-8"))
        except OSError as exc:
            raise DataError("words.txt cannot be read") from exc
    return []


def save_words(words: list[str]) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"words": words}, indent=2) + "\n"
    WORDS_JSON.write_text(payload, encoding="utf-8")
    WORDS_TXT.write_text(("\n".join(words) + "\n") if words else "", encoding="utf-8")


def _empty_catalog() -> dict:
    return {"units": [], "lessons": {}}


def load_bundled_catalog() -> dict:
    if not BUNDLED_CATALOG.exists():
        return _empty_catalog()
    try:
        data = json.loads(BUNDLED_CATALOG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DataError("catalog.json is not valid") from exc
    if not isinstance(data, dict):
        raise DataError("catalog.json is not a catalog")
    lessons = data.get("lessons") if isinstance(data.get("lessons"), dict) else {}
    units = data.get("units") if isinstance(data.get("units"), list) else []
    return {"units": units, "lessons": lessons}


def load_overlay() -> dict:
    if not LESSONS_OVERLAY.exists():
        return {}
    try:
        data = json.loads(LESSONS_OVERLAY.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DataError("lessons.json is not valid") from exc
    if isinstance(data, dict) and isinstance(data.get("lessons"), dict):
        return data["lessons"]
    if isinstance(data, dict):
        return {k: v for k, v in data.items() if isinstance(v, dict)}
    return {}


def save_overlay(lessons: dict) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    LESSONS_OVERLAY.write_text(json.dumps({"lessons": lessons}, indent=2) + "\n", encoding="utf-8")


def normalize_lesson(raw: object) -> dict | None:
    if not isinstance(raw, dict):
        return None
    lid = re.sub(r"[^A-Za-z0-9._-]", "", str(raw.get("id") or "").strip())
    if not lid:
        return None
    words = parse_words(" ".join(str(x) for x in (raw.get("words") or [])))
    hearts = parse_words(" ".join(str(x) for x in (raw.get("hearts") or [])))
    sentences = []
    for s in raw.get("sentences") or []:
        t = SAY_SAFE.sub("", str(s)).strip()
        if t:
            sentences.append(t[:180])
    chains = []
    for ch in raw.get("chains") or []:
        steps = []
        if isinstance(ch, dict):
            steps = [str(x).lower() for x in (ch.get("steps") or [])]
        elif isinstance(ch, list):
            steps = [str(x).lower() for x in ch]
        steps = [w for w in steps if WORD_RE.match(w)]
        if len(steps) >= 2:
            chains.append({"steps": steps})
    if not words and not chains and not hearts:
        return None
    title = SAY_SAFE.sub("", str(raw.get("title") or lid)).strip()[:40] or lid
    concept = SAY_SAFE.sub("", str(raw.get("concept") or "")).strip()[:80]
    unit = re.sub(r"[^A-Za-z0-9._-]", "", str(raw.get("unit") or "custom")) or "custom"
    return {
        "id": lid,
        "title": title,
        "concept": concept,
        "unit": unit,
        "words": words,
        "chains": chains,
        "hearts": hearts,
        "sentences": sentences,
    }


def load_catalog() -> dict:
    bundled = load_bundled_catalog()
    overlay = load_overlay()
    lessons = dict(bundled["lessons"])
    for lid, raw in overlay.items():
        lesson = normalize_lesson({**raw, "id": raw.get("id") or lid})
        if lesson:
            lessons[lesson["id"]] = lesson
    units = list(bundled["units"])
    if any((lessons[k].get("unit") == "custom") for k in lessons):
        if not any(u.get("id") == "custom" for u in units if isinstance(u, dict)):
            units.append({"id": "custom", "title": "Our lessons", "blurb": "Homework you add."})
    return {"units": units, "lessons": lessons}


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
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Letter-Quest-Pin")
        self.end_headers()

    def _allow_write(self) -> bool:
        provided = self.headers.get("X-Letter-Quest-Pin")
        if not provided:
            qs = parse_qs(urlparse(self.path).query)
            provided = (qs.get("pin") or [None])[0]
        if can_write(self.client_address[0], pin=PIN, provided=provided):
            return True
        self._json(403, {"ok": False, "error": "not allowed"})
        return False

    def _read_body(self) -> str | None:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length > BODY_LIMIT:
            self._json(413, {"ok": False, "error": "too large"})
            return None
        return self.rfile.read(length).decode("utf-8", "replace")

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        try:
            if path == "/api/health":
                self._json(
                    200,
                    {
                        "ok": True,
                        "words": len(load_words()),
                        "tts": bool(ESPEAK),
                        "writes": "pin" if PIN else "lan",
                    },
                )
                return
            if path == "/api/words":
                self._json(200, {"words": load_words()})
                return
            if path == "/api/lessons":
                self._json(200, load_catalog())
                return
            if path == "/api/voices":
                self._json(200, {"voices": list_voices()})
                return
        except DataError as exc:
            self._json(500, {"ok": False, "error": str(exc)})
            return
        if path == "/api/say":
            qs = parse_qs(urlparse(self.path).query)
            raw = (qs.get("t") or qs.get("text") or [""])[0]
            voice = (qs.get("v") or qs.get("voice") or [""])[0]
            wav = speak_wav(raw, voice)
            if not wav:
                self.send_error(503, "tts unavailable")
                return
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(wav)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(wav)
            return
        super().do_GET()

    def do_PUT(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/lessons":
            if self._allow_write():
                self._write_lesson()
            return
        if path == "/api/words":
            if self._allow_write():
                self._write_words()
            return
        self.send_error(404)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/lessons":
            if self._allow_write():
                self._write_lesson()
            return
        if path == "/api/words":
            if self._allow_write():
                self._write_words()
            return
        self.send_error(404)

    def do_DELETE(self) -> None:
        path = urlparse(self.path).path
        if not self._allow_write():
            return
        if path == "/api/lessons":
            qs = parse_qs(urlparse(self.path).query)
            lid = re.sub(r"[^A-Za-z0-9._-]", "", (qs.get("id") or [""])[0])
            try:
                overlay = load_overlay()
                if lid and lid in overlay:
                    del overlay[lid]
                    save_overlay(overlay)
                self._json(200, load_catalog())
            except DataError as exc:
                self._json(500, {"ok": False, "error": str(exc)})
            return
        if path != "/api/words":
            self.send_error(404)
            return
        save_words([])
        self._json(200, {"ok": True, "words": []})

    def _write_lesson(self) -> None:
        raw = self._read_body()
        if raw is None:
            return
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            self._json(400, {"ok": False, "error": "bad json"})
            return
        lesson = normalize_lesson(data)
        if not lesson:
            self._json(400, {"ok": False, "error": "need an id and some words or a chain"})
            return
        try:
            overlay = load_overlay()
            overlay[lesson["id"]] = lesson
            save_overlay(overlay)
            self._json(200, {"ok": True, "lesson": lesson, "catalog": load_catalog()})
        except DataError as exc:
            self._json(500, {"ok": False, "error": str(exc)})

    def _write_words(self) -> None:
        raw = self._read_body()
        if raw is None:
            return
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

    def stop(_signum, _frame) -> None:
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    print(f"Letter Quest  http://{HOST}:{PORT}  data={DATA}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
