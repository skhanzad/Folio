"""Layout-aware PDF extraction. No OCR and no silent content truncation."""

import hashlib
import re
import unicodedata
from collections import Counter

import pymupdf

from .models import Paper, Section

MAX_PAGES = 120
MAX_CHARS = 400_000
MAX_SECTIONS = 64

ROLE_PATTERNS = [
    ("abstract", r"^(abstract|summary)$"),
    ("related_work", r"related work|background|literature|prior work|preliminar|definition"),
    ("introduction", r"introduction|motivation|overview"),
    (
        "methods",
        r"method|approach|implementation|framework|algorithm|study design|experimental setup|materials|proof|theoretical analysis",
    ),
    ("results", r"result|experiment|evaluation|ablation|finding|benchmark|analysis"),
    ("discussion", r"discussion|limitation|ethic|broader impact|threats to validity"),
    ("conclusion", r"conclusion|future work|concluding"),
    ("references", r"^references$|^bibliography$|^works cited$"),
    ("appendix", r"appendix|appendices|supplement"),
]


class PDFError(ValueError):
    pass


def clean_heading(text: str) -> str:
    return re.sub(r"^(?:\d+(?:\.\d+)*\.?|[IVXLC]+\.)\s+", "", text).strip().rstrip(":")


def role_for(title: str) -> str:
    title = clean_heading(title).lower()
    return next((role for role, pattern in ROLE_PATTERNS if re.search(pattern, title)), "other")


def _lines(page: pymupdf.Page) -> list[dict]:
    """Read columns top-to-bottom, separated by full-width text blocks."""
    blocks = []
    mid = page.rect.width / 2
    for block in page.get_text("dict", flags=pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES)[
        "blocks"
    ]:
        if block.get("type") != 0:
            continue
        lines = []
        for line in block["lines"]:
            # Ignore rotated margin labels (e.g. the arXiv stamp), not just their font size.
            if abs(line.get("dir", (1, 0))[1]) > 0.1:
                continue
            spans = [s for s in line["spans"] if s["text"].strip()]
            if not spans:
                continue
            text = unicodedata.normalize("NFKC", "".join(s["text"] for s in line["spans"])).strip()
            lines.append(
                {
                    "text": text,
                    "size": max(s["size"] for s in spans),
                    "bold": sum(len(s["text"]) for s in spans if s["flags"] & 16)
                    >= sum(len(s["text"]) for s in spans) * 0.75,
                    "bbox": line["bbox"],
                }
            )
        if lines:
            # MuPDF can merge horizontally aligned lines from different columns
            # into one block. Split that block before establishing reading order.
            left_lines = [line for line in lines if line["bbox"][2] < mid + 8]
            right_lines = [line for line in lines if line["bbox"][0] > mid - 8]
            if left_lines and right_lines:
                wide_lines = [line for line in lines if line not in left_lines and line not in right_lines]
                for group in (left_lines, right_lines, wide_lines):
                    if group:
                        bbox = (
                            min(line["bbox"][0] for line in group),
                            min(line["bbox"][1] for line in group),
                            max(line["bbox"][2] for line in group),
                            max(line["bbox"][3] for line in group),
                        )
                        blocks.append({"bbox": bbox, "lines": group})
            else:
                blocks.append({"bbox": block["bbox"], "lines": lines})
    left = [b for b in blocks if b["bbox"][2] < mid + 8]
    right = [b for b in blocks if b["bbox"][0] > mid - 8]
    # A single right-aligned author line is not evidence of a second column.
    if sum(len(b["lines"]) for b in left) >= 6 and sum(len(b["lines"]) for b in right) >= 6:
        wide = sorted([b for b in blocks if b not in left and b not in right], key=lambda b: b["bbox"][1])
        ordered = []
        remaining = left + right
        for full in wide:
            above = [b for b in remaining if b["bbox"][1] < full["bbox"][1]]
            ordered.extend(sorted(above, key=lambda b: (b["bbox"][0] > mid - 8, b["bbox"][1])))
            remaining = [b for b in remaining if b not in above]
            ordered.append(full)
        ordered.extend(sorted(remaining, key=lambda b: (b["bbox"][0] > mid - 8, b["bbox"][1])))
    else:
        ordered = sorted(blocks, key=lambda b: (b["bbox"][1], b["bbox"][0]))
    return [line for block in ordered for line in block["lines"]]


def _heading(line: dict, body_size: float, started: bool) -> bool:
    text = line["text"]
    if len(text) > 110 or len(text.split()) > 14 or not re.search(r"[A-Za-z]", text):
        return False
    stripped = clean_heading(text)
    # Avoid treating sentences about a method or result as headings.
    if (
        role_for(stripped) != "other"
        and len(text.split()) <= 7
        and not re.search(r"[.;?!]$", text)
        and (line["bold"] or line["size"] > body_size + 0.5 or len(text.split()) <= 3)
    ):
        return True
    numbered = re.match(r"^(?:S?\d+(?:\.\d+)*\.?|[IVXLC]+\.)\s+[A-Za-z]", text)
    if numbered and line["size"] >= body_size - 0.3 and (line["bold"] or line["size"] >= body_size + 0.7):
        return True
    return bool(
        started and line["size"] >= body_size + 1.2 and line["bold"] and not re.search(r"[.;?!]$", text)
    )


def extract_pdf(data: bytes, filename: str) -> Paper:
    if not data.startswith(b"%PDF-"):
        raise PDFError("This file is not a valid PDF. Please upload a PDF document.")
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise PDFError("This PDF could not be opened. It may be damaged.") from exc
    with doc:
        if doc.needs_pass:
            raise PDFError("This PDF is password-protected. Upload an unlocked copy.")
        if not 1 <= len(doc) <= MAX_PAGES:
            raise PDFError(f"Please upload a PDF with 1–{MAX_PAGES} pages.")
        pages = [_lines(page) for page in doc]
        all_lines = [line for lines in pages for line in lines]
        if sum(len(line["text"]) for line in all_lines) > MAX_CHARS:
            raise PDFError(
                "The extracted text is too long (400,000 character limit). Split this document into smaller PDFs."
            )
        if sum(len(line["text"].split()) for line in all_lines) < 40:
            raise PDFError("Not enough readable text was found. For scanned PDFs, run OCR before uploading.")
        counts = Counter()
        for line in all_lines:
            counts[round(line["size"], 1)] += len(line["text"])
        body_size = counts.most_common(1)[0][0]
        margin_counts = Counter()
        for page_index, lines in enumerate(pages):
            margin_counts.update(
                {
                    line["text"]
                    for line in lines
                    if line["bbox"][1] < 45 or line["bbox"][3] > doc[page_index].rect.height - 40
                }
            )
        recurring = {text for text, count in margin_counts.items() if count >= max(2, len(doc) * 0.5)}
        title_candidates = [
            line
            for line in pages[0]
            if line["size"] >= body_size + 2
            and line["bbox"][1] < doc[0].rect.height * 0.3
            and role_for(line["text"]) == "other"
            and not re.match(r"^\d+\.?\s", line["text"])
        ]
        if title_candidates:
            largest = max(line["size"] for line in title_candidates)
            title = " ".join(line["text"] for line in title_candidates if line["size"] >= largest - 0.6)[:300]
        else:
            title = (doc.metadata.get("title") or filename.removesuffix(".pdf").replace("_", " "))[:300]
        warnings = []
        sparse = [
            str(i + 1)
            for i, lines in enumerate(pages)
            if sum(len(line["text"].split()) for line in lines) < 20
        ]
        if sparse:
            warnings.append(
                f"Little readable text on page(s) {', '.join(sparse)}. Scanned pages and figure content may be missing."
            )
        sections: list[Section] = []
        current: dict | None = None
        supplement = False

        def finish():
            if current and current["lines"]:
                text = "\n".join(current["lines"]).strip()
                if text:
                    sections.append(
                        Section(
                            id=f"s{len(sections) + 1}",
                            title=current["title"],
                            role=current["role"],
                            page_start=current["start"],
                            page_end=current["end"],
                            text=text,
                            word_count=len(text.split()),
                        )
                    )

        for page_index, lines in enumerate(pages):
            for line in lines:
                text = line["text"]
                if text in recurring or re.fullmatch(r"\d+", text):
                    continue
                inline_abstract = re.match(r"^(Abstract|Summary)\s*[:.—–-]\s*(.+)", text, re.IGNORECASE)
                is_heading = _heading(line, body_size, current is not None)
                if inline_abstract or is_heading:
                    # Do not score the title or author affiliations as a section.
                    if text in title or (current is None and role_for(text) == "other"):
                        continue
                    # Wrapped headings are one heading, not an empty section plus an orphan label.
                    if (
                        current
                        and not current["lines"]
                        and page_index + 1 == current["start"]
                        and not re.match(r"^(?:S?\d+|[IVXLC]+)\.", text)
                    ):
                        current["title"] += " " + text
                        continue
                    finish()
                    heading_text = inline_abstract[1] if inline_abstract else text
                    role = role_for(heading_text)
                    if role == "appendix" or re.match(r"^S\d+\.", heading_text):
                        supplement = True
                    if supplement:
                        role = "appendix"
                    if role == "other" and current and re.match(r"^\d+\.\d+", text):
                        role = current["role"]
                    current = {
                        "title": heading_text,
                        "role": role,
                        "start": page_index + 1,
                        "end": page_index + 1,
                        "lines": [],
                    }
                    if inline_abstract:
                        current["lines"].append(inline_abstract[2])
                elif current:
                    current["lines"].append(text)
                    current["end"] = page_index + 1
        finish()
        if not sections:
            warnings.append(
                "Section headings could not be identified reliably. Review units are individual pages."
            )
            for index, lines in enumerate(pages):
                text = "\n".join(line["text"] for line in lines if line["text"] not in recurring)
                if text.strip():
                    sections.append(
                        Section(
                            id=f"s{len(sections) + 1}",
                            title=f"Page {index + 1}",
                            role="other",
                            page_start=index + 1,
                            page_end=index + 1,
                            text=text,
                            word_count=len(text.split()),
                        )
                    )
        if len(sections) > MAX_SECTIONS:
            raise PDFError(
                f"This PDF has more than {MAX_SECTIONS} review units. Please split it into smaller PDFs."
            )
        return Paper(
            title=title,
            filename=filename,
            pages=len(doc),
            word_count=sum(s.word_count for s in sections),
            sha256=hashlib.sha256(data).hexdigest(),
            sections=sections,
            warnings=warnings,
        )


def chunks(text: str, limit: int = 9000) -> list[str]:
    """Bound UTF-8 bytes as a conservative context budget; retain every character."""
    result, current, size = [], [], 0
    for char in text:
        char_size = len(char.encode("utf-8"))
        if size + char_size > limit:
            result.append("".join(current))
            current, size = [], 0
        current.append(char)
        size += char_size
    if current:
        result.append("".join(current))
    return result
