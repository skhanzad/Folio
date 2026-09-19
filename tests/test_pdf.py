import pymupdf
import pytest

from server.pdf import PDFError, chunks, extract_pdf
from server.sample import sample_pdf

PARAGRAPH = (
    "This passage explains a careful approach to evaluating research with explicit assumptions and evidence. "
    * 5
)


def simple_pdf(text=PARAGRAPH, heading=None):
    with pymupdf.open() as doc:
        page = doc.new_page()
        if heading:
            page.insert_text((50, 60), heading, fontsize=14, fontname="hebo")
        page.insert_textbox(pymupdf.Rect(50, 95, 545, 500), text, fontsize=11)
        return doc.tobytes()


def test_sample_sections_and_title():
    paper = extract_pdf(sample_pdf(), "sample.pdf")
    assert paper.title == "Uncertainty-aware document classification"
    assert [s.role for s in paper.sections] == [
        "abstract",
        "introduction",
        "related_work",
        "methods",
        "results",
        "discussion",
        "conclusion",
        "references",
    ]
    assert paper.word_count == sum(s.word_count for s in paper.sections)
    assert len({s.id for s in paper.sections}) == 8
    assert all(1 <= s.page_start <= s.page_end <= paper.pages for s in paper.sections)


@pytest.mark.parametrize("content", [b"", b"not a PDF", b"%PDF-1.7\nbroken"])
def test_rejects_invalid_pdf(content):
    with pytest.raises(PDFError):
        extract_pdf(content, "bad.pdf")


def test_rejects_encrypted_pdf():
    with pymupdf.open(stream=simple_pdf(), filetype="pdf") as doc:
        encrypted = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="secret", owner_pw="owner")
    with pytest.raises(PDFError, match="password-protected"):
        extract_pdf(encrypted, "locked.pdf")


def test_scan_requires_ocr():
    with pymupdf.open() as doc:
        doc.new_page()
        data = doc.tobytes()
    with pytest.raises(PDFError, match="OCR"):
        extract_pdf(data, "scan.pdf")


def test_page_fallback_is_explicit():
    paper = extract_pdf(simple_pdf(), "no-headings.pdf")
    assert paper.sections[0].title == "Page 1"
    assert "headings" in paper.warnings[0]


def test_rotated_stamp_does_not_replace_title():
    with pymupdf.open(stream=simple_pdf(heading="1 Introduction"), filetype="pdf") as doc:
        doc[0].insert_text((50, 30), "Actual Paper Title", fontsize=17, fontname="hebo")
        doc[0].insert_text((25, 400), "arXiv:0000.00000", fontsize=23, rotate=90)
        paper = extract_pdf(doc.tobytes(), "title.pdf")
    assert paper.title == "Actual Paper Title"
    assert "arXiv" not in paper.sections[0].text


def test_table_numbers_and_list_entries_are_not_headings():
    body = "20 News\n1. Caltech-UCSD\n200 bird species.\n1.3 million/25,000/25,000\n" + PARAGRAPH
    paper = extract_pdf(simple_pdf(body, "1. Results"), "numbers.pdf")
    assert len(paper.sections) == 1
    assert paper.sections[0].role == "results"
    assert "20 News" in paper.sections[0].text


def test_inline_abstract():
    paper = extract_pdf(simple_pdf("Abstract: " + PARAGRAPH), "inline.pdf")
    assert paper.sections[0].title == "Abstract"
    assert paper.sections[0].role == "abstract"


def test_wrapped_supplement_heading():
    with pymupdf.open(stream=simple_pdf(heading="1 Introduction"), filetype="pdf") as doc:
        page = doc.new_page()
        page.insert_text((50, 60), "S1. Further Information on Calibration", fontsize=14, fontname="hebo")
        page.insert_text((65, 76), "Metrics", fontsize=14, fontname="hebo")
        page.insert_textbox(pymupdf.Rect(50, 110, 545, 500), PARAGRAPH, fontsize=11)
        paper = extract_pdf(doc.tobytes(), "supplement.pdf")
    assert paper.sections[-1].title == "S1. Further Information on Calibration Metrics"
    assert paper.sections[-1].role == "appendix"


def test_two_columns_are_read_sequentially():
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_text((50, 45), "1 Introduction", fontsize=14, fontname="hebo")
        for i in range(10):
            page.insert_text((50, 90 + i * 18), f"Left column sentence number {i}.", fontsize=10)
            page.insert_text((320, 90 + i * 18), f"Right column sentence number {i}.", fontsize=10)
        paper = extract_pdf(doc.tobytes(), "columns.pdf")
    text = paper.sections[0].text
    assert text.index("Left column sentence number 9") < text.index("Right column sentence number 0")


def test_limits_are_rejected_without_truncation(monkeypatch):
    monkeypatch.setattr("server.pdf.MAX_CHARS", 100)
    with pytest.raises(PDFError, match="too long"):
        extract_pdf(sample_pdf(), "large.pdf")


def test_page_limit(monkeypatch):
    monkeypatch.setattr("server.pdf.MAX_PAGES", 2)
    with pytest.raises(PDFError, match="1–2 pages"):
        extract_pdf(sample_pdf(), "large.pdf")


def test_section_limit(monkeypatch):
    monkeypatch.setattr("server.pdf.MAX_SECTIONS", 2)
    with pytest.raises(PDFError, match="review units"):
        extract_pdf(sample_pdf(), "many.pdf")


@pytest.mark.parametrize("text", ["some meaningful text " * 2000, "科学论文🙂é" * 5000])
def test_chunking_preserves_every_character_and_bounds_bytes(text):
    parts = chunks(text)
    assert "".join(parts) == text
    assert all(len(part.encode("utf-8")) <= 9000 for part in parts)
