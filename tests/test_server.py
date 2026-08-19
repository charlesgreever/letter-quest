#!/usr/bin/env python3
"""Public-behavior tests for the Letter Quest server (ENG-04)."""
from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_server(data_dir: Path):
    os.environ["DATA_DIR"] = str(data_dir)
    os.environ.pop("LETTER_QUEST_PIN", None)
    import server as srv

    importlib.reload(srv)
    srv.DATA = data_dir
    srv.WORDS_JSON = data_dir / "words.json"
    srv.WORDS_TXT = data_dir / "words.txt"
    srv.LESSONS_OVERLAY = data_dir / "lessons.json"
    return srv


class ParseAndLessonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.srv = _load_server(Path(self.tmp.name))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_parse_words_keeps_unique_lowercase_letters_only(self) -> None:
        got = self.srv.parse_words("Sun, SUN!  glum\n42 plug?")
        self.assertEqual(got, ["sun", "glum", "plug"])

    def test_normalize_lesson_requires_id_and_content(self) -> None:
        self.assertIsNone(self.srv.normalize_lesson({"title": "Nope"}))
        self.assertIsNone(self.srv.normalize_lesson({"id": "42b"}))

    def test_normalize_lesson_keeps_a_chain_and_hearts(self) -> None:
        lesson = self.srv.normalize_lesson(
            {
                "id": "39b",
                "title": "Short U <b>Advanced</b>",
                "concept": "short u advanced review",
                "words": ["spun", "plum"],
                "chains": [{"steps": ["glum", "plum", "plug"]}],
                "hearts": ["look"],
                "sentences": ["The cubs are fast."],
            }
        )
        assert lesson is not None
        self.assertEqual(lesson["id"], "39b")
        self.assertNotIn("<", lesson["title"])
        self.assertEqual(lesson["chains"][0]["steps"], ["glum", "plum", "plug"])
        self.assertEqual(lesson["hearts"], ["look"])


class FailClosedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.srv = _load_server(Path(self.tmp.name))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_corrupt_words_json_is_not_treated_as_an_empty_list(self) -> None:
        self.srv.WORDS_JSON.write_text("{not json", encoding="utf-8")
        with self.assertRaises(self.srv.DataError):
            self.srv.load_words()

    def test_missing_words_file_is_an_empty_list(self) -> None:
        self.assertEqual(self.srv.load_words(), [])

    def test_corrupt_overlay_is_not_treated_as_no_lessons(self) -> None:
        self.srv.LESSONS_OVERLAY.write_text("{nope", encoding="utf-8")
        with self.assertRaises(self.srv.DataError):
            self.srv.load_overlay()


class WriteGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.srv = _load_server(Path(self.tmp.name))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_lan_can_write_without_a_pin(self) -> None:
        self.assertTrue(self.srv.can_write("127.0.0.1", pin="", provided=None))
        self.assertTrue(self.srv.can_write("192.168.1.95", pin="", provided=None))
        self.assertTrue(self.srv.can_write("10.0.0.4", pin="", provided=None))
        self.assertTrue(self.srv.can_write("172.16.8.2", pin="", provided=None))

    def test_public_ip_cannot_write_without_a_pin(self) -> None:
        self.assertFalse(self.srv.can_write("8.8.8.8", pin="", provided=None))

    def test_pin_is_required_when_set_and_does_not_say_why(self) -> None:
        self.assertTrue(self.srv.can_write("8.8.8.8", pin="secret", provided="secret"))
        self.assertFalse(self.srv.can_write("8.8.8.8", pin="secret", provided="wrong"))
        self.assertFalse(self.srv.can_write("127.0.0.1", pin="secret", provided=None))


class VoiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.srv = _load_server(Path(self.tmp.name))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_known_voice_maps_to_an_espeak_name(self) -> None:
        self.assertEqual(self.srv.resolve_voice("annie"), "en-us+Annie")

    def test_unknown_or_nasty_voice_falls_back_to_teacher(self) -> None:
        self.assertEqual(self.srv.resolve_voice("hax;rm -rf"), self.srv.resolve_voice("teacher"))
        self.assertEqual(self.srv.resolve_voice(None), self.srv.resolve_voice("teacher"))


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.srv = _load_server(Path(self.tmp.name))
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), self.srv.Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.httpd.server_address[:2]
        self.base = f"http://{host}:{port}"

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmp.cleanup()

    def _json(self, method: str, path: str, body: object | None = None, pin: str | None = None) -> tuple[int, object]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if pin is not None:
            headers["X-Letter-Quest-Pin"] = pin
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=4) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            raw = err.read().decode("utf-8", "replace")
            try:
                return err.code, json.loads(raw)
            except json.JSONDecodeError:
                return err.code, raw

    def test_health_reports_tts_flag(self) -> None:
        code, body = self._json("GET", "/api/health")
        self.assertEqual(code, 200)
        self.assertTrue(body["ok"])
        self.assertIn("tts", body)

    def test_voices_list_includes_teacher_and_annie(self) -> None:
        code, body = self._json("GET", "/api/voices")
        self.assertEqual(code, 200)
        ids = [v["id"] for v in body["voices"]]
        self.assertIn("teacher", ids)
        self.assertIn("annie", ids)

    def test_post_lesson_then_get_catalog_includes_it(self) -> None:
        code, body = self._json(
            "POST",
            "/api/lessons",
            {
                "id": "42b",
                "title": "Test Add",
                "words": ["sun", "bug"],
                "chains": [{"steps": ["sun", "run"]}],
                "hearts": ["was"],
            },
        )
        self.assertEqual(code, 200)
        self.assertTrue(body["ok"])
        code, cat = self._json("GET", "/api/lessons")
        self.assertEqual(code, 200)
        self.assertIn("42b", cat["lessons"])
        self.assertEqual(cat["lessons"]["42b"]["words"], ["sun", "bug"])

    def test_delete_custom_lesson_removes_only_that_id(self) -> None:
        self._json("POST", "/api/lessons", {"id": "99", "words": ["cat"]})
        code, cat = self._json("DELETE", "/api/lessons?id=99")
        self.assertEqual(code, 200)
        self.assertNotIn("99", cat["lessons"])

    def test_put_unknown_path_is_not_a_word_save(self) -> None:
        code, _ = self._json("PUT", "/api/nope", {"words": ["sun"]})
        self.assertEqual(code, 404)
        self.assertEqual(self.srv.load_words(), [])

    def test_oversized_body_is_rejected(self) -> None:
        code, body = self._json("POST", "/api/lessons", {"id": "x", "words": ["aa"] * 20000})
        self.assertEqual(code, 413)
        self.assertFalse(body["ok"])


if __name__ == "__main__":
    unittest.main()
