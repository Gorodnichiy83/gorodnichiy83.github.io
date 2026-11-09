#!/usr/bin/env python3
"""Build the printable HTML and searchable PDF from index.html alone.

Run: python build_resume.py --source index.html --output-dir _site
Only resume.html and pavel-gorodnichiy-resume.pdf are written. Static assets
must be copied by the caller. Onest TTFs are bundled under SIL OFL (OFL.txt),
instantiated at 400/600/700 from google/fonts/ofl/onest/Onest[wght].ttf.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from hashlib import sha256
from html import escape
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from urllib.parse import urljoin, urlsplit

from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    BaseDocTemplate, Frame, Image, PageBreak, PageTemplate, Paragraph, Spacer,
    Table, TableStyle,
)

ROOT = Path(__file__).resolve().parent
PDF_NAME = "pavel-gorodnichiy-resume.pdf"
INK = colors.HexColor("#183e34")
MUTED = colors.HexColor("#647167")
LINE = colors.HexColor("#d4d9cd")
SAGE = colors.HexColor("#edf1e6")
PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN = 42
CONTENT_WIDTH = PAGE_WIDTH - 2 * MARGIN


def clean(text: str) -> str:
    return " ".join(text.split())


def comparable(text: str) -> str:
    return re.sub(r"\s+", "", text)


@dataclass
class Node:
    tag: str = ""
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)

    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.walk()

    def select(self, *, tag=None, cls=None, id=None):
        return [n for n in self.walk() if
                (tag is None or n.tag == tag) and
                (cls is None or cls in n.attrs.get("class", "").split()) and
                (id is None or n.attrs.get("id") == id)]

    def text(self):
        if self.tag in {"svg", "script", "style"}:
            return ""
        return clean(" ".join(c if isinstance(c, str) else c.text()
                              for c in self.children))

    def one(self, **selector):
        nodes = self.select(**selector)
        if len(nodes) != 1:
            raise ValueError(f"Expected one {selector}, found {len(nodes)}")
        return nodes[0]


class DocumentParser(HTMLParser):
    """Reject malformed markup instead of silently building a partial resume."""
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input",
            "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]
        self.ids = set()
        self.feed(source)
        self.close()
        if len(self.stack) != 1:
            raise ValueError(f"Unclosed HTML element: {self.stack[-1].tag}")

    def handle_starttag(self, tag, attrs):
        if len(dict(attrs)) != len(attrs):
            raise ValueError(f"Duplicate attribute in <{tag}>")
        node = Node(tag, dict(attrs))
        identifier = node.attrs.get("id")
        if identifier:
            if identifier in self.ids:
                raise ValueError(f"Duplicate HTML id: {identifier}")
            self.ids.add(identifier)
        self.stack[-1].children.append(node)
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_endtag(self, tag):
        if len(self.stack) == 1 or self.stack[-1].tag != tag:
            raise ValueError(f"Unexpected closing element: {tag}")
        self.stack.pop()

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def content(node, evidence, label):
    text = node.text()
    if not text:
        raise ValueError(f"Empty required content: {label}")
    evidence.append(text)
    return text


def local_asset(source: Path, reference: str) -> Path:
    parsed = urlsplit(reference)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError(f"Expected a local asset path: {reference}")
    target = (source.parent / parsed.path).resolve()
    if not target.is_relative_to(source.parent.resolve()) or not target.is_file():
        raise ValueError(f"Missing or unsafe asset: {reference}")
    return target


def website_url(tree):
    canonical = [n.attrs.get("href") for n in tree.select(tag="link")
                 if "canonical" in n.attrs.get("rel", "").split()]
    og_url = [n.attrs.get("content") for n in tree.select(tag="meta")
              if n.attrs.get("property") == "og:url"]
    images = [n.attrs.get("content") for n in tree.select(tag="meta")
              if n.attrs.get("property") == "og:image"]
    candidates = canonical or og_url
    if not candidates and len(images) == 1:
        candidates = [urljoin(images[0], ".")]
    if len(candidates) != 1:
        raise ValueError("Provide one canonical URL or og:url in index.html")
    url = candidates[0]
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.query or parsed.fragment:
        raise ValueError("The resume website URL must be an absolute HTTPS URL")
    return url


def extract_model(source: Path):
    raw = source.read_bytes()
    tree = DocumentParser(raw.decode("utf-8")).root
    evidence = []
    take = lambda node, label: content(node, evidence, label)
    hero = tree.one(id="top")
    results = tree.one(id="results")
    career_section = tree.one(id="experience")
    education = tree.one(id="education")
    contact_section = tree.one(id="contact")
    approach = tree.one(id="approach")
    photo = hero.one(cls="profile-photo").attrs.get("src", "")
    local_asset(source, photo)
    location = hero.one(cls="hero-location")
    location_parts = [n for n in location.children if isinstance(n, Node)
                      and "location-mark" not in n.attrs.get("class", "").split()]
    if len(location_parts) != 1:
        raise ValueError("Expected one location text block")
    model = {
        "name": take(hero.one(tag="h1"), "name"),
        "role": take(hero.one(cls="hero-role"), "role"),
        "description": take(hero.one(cls="hero-description"), "description"),
        "experience": take(hero.one(cls="portrait-note"), "experience"),
        "location": take(location_parts[0], "location"),
        "photo": photo,
        "website": website_url(tree),
        "companies": [take(n, "company") for n in tree.one(cls="companies").select(tag="li")],
        "results_title": take(results.one(tag="h2"), "results title"),
        "results_intro": take(results.one(cls="section-intro"), "results intro"),
        "cases": [], "careers": [], "contacts": [],
        "source_sha256": sha256(raw).hexdigest(),
    }
    for link in contact_section.select(tag="a"):
        href = link.attrs.get("href", "")
        if href.startswith(("mailto:", "tel:")):
            if not href.split(":", 1)[1].strip():
                raise ValueError("Empty contact URL")
            model["contacts"].append({"text": take(link, "contact"), "href": href})
    if not model["contacts"]:
        raise ValueError("No contact links found")
    for case in results.select(cls="case"):
        summary = case.one(tag="summary")
        top = summary.one(cls="case-top")
        top_spans = [n for n in top.children if isinstance(n, Node) and n.tag == "span"]
        if len(top_spans) != 2:
            raise ValueError("Expected company and ordinal in case-top")
        data = {
            "company": take(top_spans[0], "case company"),
            "ordinal": take(top_spans[1], "case ordinal"),
            "metric": take(summary.one(cls="case-number"), "case metric").replace(" %", "%"),
            "title": take(summary.one(tag="h3"), "case title"),
            "summary": take(summary.one(tag="p"), "case summary"),
            "body": [],
        }
        for child in case.one(cls="case-body").children:
            if isinstance(child, str):
                if child.strip():
                    raise ValueError("Unexpected raw text in case-body")
                continue
            text = take(child, "case detail")
            classes = child.attrs.get("class", "").split()
            if child.tag == "p":
                label_nodes = [n for n in child.children if isinstance(n, Node) and n.tag == "strong"]
                label = label_nodes[0].text() if label_nodes and child.select(tag="br") else ""
                body = clean(text[len(label):]) if label else text
                data["body"].append({"kind": "paragraph", "label": label, "text": body})
            elif "case-fact" in classes or "time-comparison" in classes:
                data["body"].append({"kind": "fact", "label": "", "text": text})
            else:
                raise ValueError(f"Unsupported case detail: {child.tag} {classes}")
        if len([b for b in data["body"] if b["label"]]) < 2:
            raise ValueError("Every case needs role and solution details")
        model["cases"].append(data)
    for career in career_section.select(cls="career-item"):
        data = {key: take(career.one(cls=cls), key) for key, cls in
                [("date", "career-date"), ("company", "company"),
                 ("role", "career-role"), ("sector", "sector")]}
        data["bullets"] = [take(li, "career achievement") for li in career.one(cls="career-content").select(tag="li")]
        if not data["bullets"]:
            raise ValueError(f"No career achievements: {data['company']}")
        model["careers"].append(data)
    degree = education.one(cls="degree")
    model["degree"] = {"label": take(degree.one(cls="eyebrow"), "degree label"),
                       "name": take(degree.one(tag="h3"), "degree name"),
                       "description": take(degree.one(tag="p"), "degree description")}
    model["language"] = take(education.one(cls="language"), "language")
    model["training"] = []
    for item in education.one(cls="training-list").select(tag="li"):
        model["training"].append({"year": take(item.one(tag="span"), "course year"),
                                  "text": take(item.one(tag="div"), "course")})
    model["approach_title"] = take(approach.one(tag="h2"), "approach title")
    intro = approach.one(cls="approach-intro")
    model["approach_intro"] = [take(n, "approach intro") for n in intro.children
                               if isinstance(n, Node) and n.tag == "p" and
                               "eyebrow" not in n.attrs.get("class", "").split()]
    model["expertise"] = [{"title": take(n.one(tag="h3"), "expertise title"),
                            "text": take(n.one(tag="p"), "expertise")}
                           for n in approach.one(cls="expertise-list").select(tag="article")]
    model["industries"] = [take(n, "industry") for n in approach.one(cls="industry-tags").select(tag="span")]
    model["steps"] = [take(n, "method step") for n in approach.one(cls="method-line").select(tag="span")
                      if n.attrs.get("aria-hidden") != "true"]
    for key in ("cases", "careers", "companies", "training", "expertise"):
        if not model[key]:
            raise ValueError(f"Missing essential content: {key}")
    model["evidence"] = evidence
    return model


def html_resume(model):
    e = escape
    paragraph = lambda text: f"<p>{e(text)}</p>"
    contact_links = " · ".join(f'<a href="{e(c["href"], quote=True)}">{e(c["text"])}</a>'
                               for c in model["contacts"])
    sections = []
    cases = []
    for case in model["cases"]:
        blocks = "".join(f'<p class="{b["kind"]}">'
                         + (f'<strong>{e(b["label"])}</strong> ' if b["label"] else "")
                         + e(b["text"]) + "</p>" for b in case["body"])
        cases.append(f'<article class="result-card"><div class="case-top"><span>{e(case["company"])}</span><span>{e(case["ordinal"])}</span></div>'
                     f'<div class="case-heading"><strong class="case-metric">{e(case["metric"])}</strong><h3>{e(case["title"])}</h3></div>'
                     f'<p class="case-summary">{e(case["summary"])}</p>{blocks}</article>')
    sections.append(f'<section class="results"><h2>{e(model["results_title"])}</h2>'
                    f'{paragraph(model["results_intro"])}<div class="case-list">{"".join(cases)}</div></section>')
    careers = []
    for career in model["careers"]:
        bullets = "".join(f"<li>{e(text)}</li>" for text in career["bullets"])
        careers.append(f'<article class="career-item"><div class="career-head"><span class="career-date">{e(career["date"])}</span>'
                       f'<div><h3>{e(career["company"])}</h3><p class="career-role">{e(career["role"])}</p></div></div>'
                       f'<div class="career-content"><p class="sector">{e(career["sector"])}</p><ul>{bullets}</ul></div></article>')
    sections.append(f'<section class="career"><h2>Опыт работы</h2>{"".join(careers)}</section>')
    expertise = "".join(f'<article><h3>{e(item["title"])}</h3>{paragraph(item["text"])}</article>' for item in model["expertise"])
    sections.append(f'<section class="approach"><h2>{e(model["approach_title"])}</h2>'
                    + "".join(paragraph(t) for t in model["approach_intro"])
                    + f'<p class="industries">{e(" · ".join(model["industries"]))}</p><div class="expertise">{expertise}</div>'
                    + f'<p class="method">{e(" → ".join(model["steps"]))}</p></section>')
    degree = model["degree"]
    training = "".join(f'<li><span>{e(t["year"])}</span><p>{e(t["text"])}</p></li>' for t in model["training"])
    sections.append(f'<section class="education"><h2>Образование и развитие</h2><p class="eyebrow">{e(degree["label"])}</p>'
                    f'<h3>{e(degree["name"])}</h3>{paragraph(degree["description"])}{paragraph(model["language"])}'
                    f'<h3 class="training-heading">Профильное обучение</h3><ul class="training-list">{training}</ul></section>')
    return f'''<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="source-sha256" content="{model['source_sha256']}"><title>Резюме — {e(model['name'])}</title>
<link rel="stylesheet" href="resume.css"></head><body>
<div class="toolbar"><a href="./">← Вернуться к визитке</a><a href="{PDF_NAME}" download>Скачать резюме PDF ↓</a><span>Печать: Ctrl / ⌘ + P</span></div>
<main><header><div><h1>{e(model['name'])}</h1><p class="position">{e(model['role'])}</p><p class="contacts">{contact_links}</p>
<p>{e(model['location'])}</p><p><a href="{e(model['website'], quote=True)}">{e(model['website'])}</a></p></div><img src="{e(model['photo'], quote=True)}" alt="{e(model['name'], quote=True)}" width="110" height="110"></header>
<div class="profile"><p class="experience">{e(model['experience'])}</p>{paragraph(model['description'])}
<p class="companies">{e(' · '.join(model['companies']))}</p></div>
{''.join(sections)}
<footer><strong>{e(model['name'])}</strong><p>{contact_links}</p><a href="{e(model['website'], quote=True)}">{e(model['website'])}</a></footer>
</main></body></html>'''


def register_fonts():
    for name, filename in (("Onest", "onest-regular.ttf"), ("Onest-Semibold", "onest-semibold.ttf"), ("Onest-Bold", "onest-bold.ttf")):
        pdfmetrics.registerFont(TTFont(name, str(ROOT / filename)))
    pdfmetrics.registerFontFamily("Onest", normal="Onest", bold="Onest-Bold", italic="Onest", boldItalic="Onest-Bold")


def make_styles():
    def style(name, size=9.5, leading=13.2, **options):
        defaults = dict(fontName="Onest", fontSize=size, leading=leading,
                        textColor=INK, spaceAfter=4)
        defaults.update(options)
        return ParagraphStyle(name, **defaults)
    return {
        "body": style("body"),
        "small": style("small", 8.4, 11.4, textColor=MUTED),
        "name": style("name", 27, 31, fontName="Onest-Semibold"),
        "role": style("role", 11, 15, fontName="Onest-Semibold"),
        "section": style("section", 17, 21, fontName="Onest-Semibold", spaceBefore=13, keepWithNext=True),
        "company": style("company", 12, 16, fontName="Onest-Semibold", keepWithNext=True, spaceBefore=10),
        "career_role": style("career-role", 9.5, 13.2, keepWithNext=True),
        "bullet": style("bullet", leftIndent=11, firstLineIndent=-11, bulletIndent=0),
        "metric": style("metric", 25, 29, fontName="Onest-Semibold"),
        "case_title": style("case-title", 12, 16, fontName="Onest-Semibold"),
        "case_company": style("case-company", 10.5, 14.5, fontName="Onest-Semibold", spaceBefore=10, keepWithNext=True),
        "case_body": style("case-body", 9.1, 12.5),
        "fact": style("fact", 9.4, 13, fontName="Onest-Semibold"),
        "expert_title": style("expert-title", 10.2, 14, fontName="Onest-Semibold", spaceBefore=6, keepWithNext=True),
        "footer": style("footer", 7.2, 9.5, textColor=MUTED),
    }


class NumberedCanvas(Canvas):
    def __init__(self, *args, model, **kwargs):
        kwargs["invariant"] = 1
        super().__init__(*args, **kwargs)
        self.model = model
        self.saved_pages = []

    def showPage(self):
        self.saved_pages.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        page_count = len(self.saved_pages)
        for state in self.saved_pages:
            self.__dict__.update(state)
            self.setStrokeColor(LINE)
            self.setLineWidth(.5)
            self.line(MARGIN, 37, PAGE_WIDTH - MARGIN, 37)
            self.setFillColor(MUTED)
            self.setFont("Onest", 7.5)
            self.drawString(MARGIN, 23, urlsplit(self.model["website"]).netloc)
            self.drawRightString(PAGE_WIDTH - MARGIN, 23, f"{self._pageNumber} / {page_count}")
            super().showPage()
        super().save()


def pdf_resume(model, source: Path, destination: Path):
    register_fonts()
    styles = make_styles()
    p = lambda text, kind="body": Paragraph(text, styles[kind])
    plain = lambda text, kind="body": p(escape(text), kind)
    contacts = " · ".join(f'<link href="{escape(c["href"], quote=True)}">{escape(c["text"])}</link>' for c in model["contacts"])
    website = f'<link href="{escape(model["website"], quote=True)}">{escape(model["website"])}</link>'
    hero = [plain(model["name"], "name"), plain(model["role"], "role"), Spacer(1, 5),
            p(contacts, "small"), plain(model["location"], "small"), p(website, "small")]
    photo = Image(str(local_asset(source, model["photo"])), width=85, height=85)
    table = Table([[hero, photo]], colWidths=[CONTENT_WIDTH - 103, 103])
    table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                               ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    story = [table, Spacer(1, 8), p(f'<b>{escape(model["experience"])}</b>'),
             plain(model["description"]), plain(" · ".join(model["companies"]), "small"),
             plain(model["results_title"], "section"), plain(model["results_intro"], "small")]
    for case in model["cases"]:
        story.append(plain(f'{case["ordinal"]} / {case["company"]}', "case_company"))
        heading = Table([[plain(case["metric"], "metric"), plain(case["title"], "case_title")]], colWidths=[130, CONTENT_WIDTH - 130])
        heading.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                    ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                                    ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                                    ("LINEBELOW", (0, 0), (-1, -1), .5, LINE)]))
        heading.keepWithNext = True
        story.extend([heading, plain(case["summary"], "small")])
        for block in case["body"]:
            text = (f'<b>{escape(block["label"])}</b> ' if block["label"] else "") + escape(block["text"])
            story.append(p(text, "fact" if block["kind"] == "fact" else "case_body"))
    career_groups = []
    for career in model["careers"]:
        group = [p(f'<font size="8.5" color="#647167">{escape(career["date"])}</font>  {escape(career["company"])}', "company"),
                 plain(career["role"], "career_role")]
        sector = plain(career["sector"], "small")
        sector.keepWithNext = True
        group.append(sector)
        for bullet in career["bullets"]:
            group.append(Paragraph(escape(bullet), styles["bullet"], bulletText="•"))
        career_groups.append(group)
    # Balance two career pages when complete entries fit; longer future content
    # uses normal paragraph splitting instead of being trapped in a large table.
    heights = [sum(item.wrap(CONTENT_WIDTH, 100000)[1] + item.getSpaceBefore() + item.getSpaceAfter()
                   for item in group) for group in career_groups]
    available = PAGE_HEIGHT - 42 - 49 - 42
    split_at = None
    if available < sum(heights) <= available * 2 and len(heights) > 1:
        candidates = [i for i in range(1, len(heights))
                      if max(sum(heights[:i]), sum(heights[i:])) <= available]
        if candidates:
            split_at = min(candidates, key=lambda i: abs(sum(heights[:i]) - sum(heights[i:])))
    story.extend([PageBreak(), plain("Опыт работы", "section")])
    for i, group in enumerate(career_groups):
        if i == split_at:
            story.extend([PageBreak(), plain("Опыт работы", "section")])
        story.extend(group)
    story.extend([PageBreak(), plain(model["approach_title"], "section")])
    story.extend(plain(text) for text in model["approach_intro"])
    story.append(plain(" · ".join(model["industries"]), "small"))
    for item in model["expertise"]:
        story.extend([plain(item["title"], "expert_title"), plain(item["text"])])
    story.append(plain(" → ".join(model["steps"]), "small"))
    degree = model["degree"]
    story.extend([plain("Образование и развитие", "section"), plain(degree["label"], "small"),
                  plain(degree["name"], "expert_title"), plain(degree["description"]),
                  plain(model["language"]), plain("Профильное обучение", "expert_title")])
    for item in model["training"]:
        story.append(p(f'<font color="#647167">{escape(item["year"])}</font>  {escape(item["text"])}'))
    story.extend([Spacer(1, 9), plain("Контакты", "expert_title"), plain(model["name"]), p(contacts), p(website)])
    document = BaseDocTemplate(str(destination), pagesize=A4, title=f'{model["name"]} — {model["role"]}',
                               author=model["name"], subject=f'Resume source SHA256: {model["source_sha256"]}',
                               leftMargin=MARGIN, rightMargin=MARGIN, topMargin=42, bottomMargin=49,
                               pageCompression=1)
    frame = Frame(MARGIN, 49, CONTENT_WIDTH, PAGE_HEIGHT - 42 - 49, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    def decorate(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(INK)
        canvas.rect(0, PAGE_HEIGHT - 7, PAGE_WIDTH, 7, fill=1, stroke=0)
        if doc.page > 1:
            canvas.setFont("Onest", 7.5)
            canvas.setFillColor(MUTED)
            canvas.drawString(MARGIN, PAGE_HEIGHT - 25, model["name"])
        canvas.restoreState()
    document.addPageTemplates(PageTemplate(id="resume", frames=[frame], onPage=decorate))
    document.build(story, canvasmaker=lambda *a, **kw: NumberedCanvas(*a, model=model, **kw))


def validate_outputs(model, html_path: Path, pdf_path: Path):
    html_tree = DocumentParser(html_path.read_text(encoding="utf-8")).root
    html_text = comparable(html_tree.one(tag="main").text())
    reader = PdfReader(pdf_path)
    page_texts = []
    footer = re.compile(re.escape(urlsplit(model["website"]).netloc) + r"\s*\n\d+\s*/\s*\d+\s*$")
    for index, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        if index:
            text = text.removeprefix(model["name"] + "\n")
        page_texts.append(footer.sub("", text))
    # Ignore only our known running headers/footers so a paragraph that crosses
    # a page boundary still participates in the same full-content comparison.
    pdf_text = comparable(" ".join(page_texts))
    evidence = model["evidence"] + [model["website"]]
    missing_html = [t for t in evidence if comparable(t) not in html_text]
    missing_pdf = [t for t in evidence if comparable(t) not in pdf_text]
    annotations = [a.get_object().get("/A", {}).get("/URI") for page in reader.pages for a in page.get("/Annots", [])]
    required = {model["website"]} | {c["href"] for c in model["contacts"]}
    missing_links = sorted(required - set(annotations))
    if missing_html or missing_pdf or missing_links or not reader.pages:
        preview = lambda texts: [t if len(t) < 200 else t[:197] + "..." for t in texts]
        raise ValueError(json.dumps({"missing_html": preview(missing_html), "missing_pdf": preview(missing_pdf),
                                     "missing_links": missing_links}, ensure_ascii=False))
    return {"pages": len(reader.pages), "cases": len(model["cases"]), "careers": len(model["careers"]),
            "courses": len(model["training"]), "coverage_checks": len(evidence),
            "source_sha256": model["source_sha256"], "pdf_sha256": sha256(pdf_path.read_bytes()).hexdigest(),
            "required_links_present": True}


def build(source: Path, output_dir: Path):
    source = source.resolve()
    model = extract_model(source)
    output_dir.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".resume-build-", dir=output_dir) as temporary:
        directory = Path(temporary)
        html_path, pdf_path = directory / "resume.html", directory / PDF_NAME
        html_path.write_text(html_resume(model), encoding="utf-8")
        pdf_resume(model, source, pdf_path)
        result = validate_outputs(model, html_path, pdf_path)
        os.replace(html_path, output_dir / html_path.name)
        os.replace(pdf_path, output_dir / pdf_path.name)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("index.html"))
    parser.add_argument("--output-dir", type=Path, default=Path("."))
    args = parser.parse_args()
    try:
        print(json.dumps(build(args.source, args.output_dir), ensure_ascii=False))
    except (ValueError, OSError) as error:
        parser.exit(1, f"Resume build failed: {error}\n")


if __name__ == "__main__":
    main()
