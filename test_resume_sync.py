"""Regression checks for editing only index.html and downloading a fresh PDF."""

from pathlib import Path
from html import unescape
import re
import shutil
import tempfile
import unittest

from pypdf import PdfReader

from build_site import build, PDF_NAME


ROOT = Path(__file__).resolve().parent


class ResumeSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        shutil.copytree(ROOT, self.source, ignore=shutil.ignore_patterns(
            ".git", "_site", "__pycache__", ".venv"))

    def test_one_source_updates_pdf_and_print_version(self):
        before = self.root / "before"
        build(self.source, before)
        original_pdf = (before / PDF_NAME).read_bytes()
        source = self.source / "index.html"
        html = source.read_text(encoding="utf-8")
        first_course = re.search(r'<ul class="training-list">\s*<li>.*?<strong>(.*?)</strong>',
                                 html, flags=re.DOTALL)
        self.assertIsNotNone(first_course)
        old_course_name = unescape(re.sub(r'<[^>]+>', '', first_course[1])).strip()
        html, count = re.subn(r'(<h3[^>]*>).*?(</h3>)',
                             r'\1Проверка обновления кейса\2', html, count=1,
                             flags=re.DOTALL)
        self.assertEqual(count, 1)
        html, count = re.subn(r'(<span class="career-role">).*?(</span>)',
                             r'\1Проверка обновления должности\2', html, count=1,
                             flags=re.DOTALL)
        self.assertEqual(count, 1)
        html, count = re.subn(r'(<ul class="training-list">)\s*<li>.*?</li>',
                             r'\1<li><span>2099</span><div><strong>Тестовый новый курс</strong> · Тест</div></li>',
                             html, count=1, flags=re.DOTALL)
        self.assertEqual(count, 1)
        source.write_text(html, encoding="utf-8")
        after = self.root / "after"
        build(self.source, after)
        pdf = after / PDF_NAME
        text = " ".join(" ".join(page.extract_text() for page in PdfReader(pdf).pages).split())
        print_html = (after / "resume.html").read_text(encoding="utf-8")
        for expected in ("Проверка обновления кейса", "Проверка обновления должности", "Тестовый новый курс"):
            self.assertIn(expected, text)
            self.assertIn(expected, print_html)
        if old_course_name not in unescape(html):
            self.assertNotIn(old_course_name, text)
            self.assertNotIn(old_course_name, unescape(print_html))
        self.assertNotEqual(original_pdf, pdf.read_bytes())
        self.assertNotEqual((before / "index.html").read_bytes(), (after / "index.html").read_bytes())
        self.assertRegex((after / "index.html").read_text(), r'pavel-gorodnichiy-resume\.pdf\?v=[0-9a-f]{16}')
        self.assertEqual(source.read_text(), html, "Building must not modify the editable source")
        repeated = self.root / "repeated"
        build(self.source, repeated)
        self.assertEqual(pdf.read_bytes(), (repeated / PDF_NAME).read_bytes())

    def test_missing_source_content_stops_publication(self):
        source = self.source / "index.html"
        source.write_text('<!doctype html><html lang="ru"><body><h1>Incomplete source</h1></body></html>')
        with self.assertRaises(Exception):
            build(self.source, self.root / "incomplete")


if __name__ == "__main__":
    unittest.main()
