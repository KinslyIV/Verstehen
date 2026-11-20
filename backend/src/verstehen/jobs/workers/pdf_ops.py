import io
import re
from contextlib import closing, contextmanager
from pathlib import Path
from threading import Lock
from typing import Any

import pypdfium2 as pdfium
import regex

from verstehen.teaching.files.access import regular_file

PDFIUM_LOCK = Lock()


@contextmanager
def open_pdf(path: Path):
    with PDFIUM_LOCK, regular_file(path) as stream:
        with pdfium.PdfDocument(stream.read()) as document:
            yield document


def page_numbers(spec: str, total: int) -> list[int]:
    if spec.strip().lower() == "all":
        return list(range(1, total + 1))
    pages: set[int] = set()
    for part in spec.split(","):
        match = re.fullmatch(r"\s*(\d+)\s*(?:-\s*(\d+)\s*)?", part)
        if match:
            start = max(1, int(match[1]))
            end = min(total, int(match[2] or match[1]))
            pages.update(range(start, end + 1))
    return sorted(pages)


def page_text(page: Any) -> str:
    with closing(page.get_textpage()) as textpage:
        return textpage.get_text_range().replace("\r\n", "\n")


def pdf_info(path: Path) -> dict[str, Any]:
    pages = []
    with open_pdf(path) as document:
        for index in range(len(document)):
            with closing(document[index]) as page:
                text = page_text(page)
                math = len(
                    re.findall(
                        r"[\u2200-\u22ff\u2100-\u214f\u2190-\u21ff\u27c0-\u27ef\u2980-\u29ff\u2a00-\u2aff\u0370-\u03ff\U0001d400-\U0001d7ff∫∑∏√∂∇∞≈≠≤≥±×÷∈∉⊂⊃∪∩∧∨¬∀∃∅]",
                        text,
                    )
                )
                pages.append(
                    {
                        "page": index + 1,
                        "text_length": len(text),
                        "image_count": sum(
                            1
                            for obj in page.get_objects()
                            if isinstance(obj, pdfium.PdfImage)
                        ),
                        "math_density": round(math / max(1, len(text)), 4),
                    }
                )
    return {
        "path": str(path),
        "page_count": len(pages),
        "mean_text_length": round(
            sum(p["text_length"] for p in pages) / max(1, len(pages))
        ),
        "pages": pages,
    }


def pdf_extract(path: Path, spec: str) -> tuple[str, list[int]]:
    chunks = []
    with open_pdf(path) as document:
        numbers = page_numbers(spec, len(document))
        for number in numbers:
            with closing(document[number - 1]) as page:
                chunks.append(f"--- Page {number} ---\n{page_text(page)}")
    return "\n".join(
        chunks
    ) or "No pages selected — page spec matched nothing.", numbers


def pdf_search(
    path: Path, query: str, context_lines: int = 3, literal: bool = False
) -> list[dict[str, Any]]:
    try:
        pattern = regex.compile(regex.escape(query) if literal else query, regex.I)
    except regex.error as error:
        raise ValueError(f"Invalid regex: {error}") from error
    hits = []
    with open_pdf(path) as document:
        for index in range(len(document)):
            with closing(document[index]) as page:
                lines = page_text(page).split("\n")
            for line, value in enumerate(lines):
                if pattern.search(value, timeout=1):
                    start, end = (
                        max(0, line - context_lines),
                        min(len(lines), line + context_lines + 1),
                    )
                    hits.append(
                        {
                            "page": index + 1,
                            "line": line + 1,
                            "context": "\n".join(
                                f"{'>>>' if j == line else '   '} {lines[j]}"
                                for j in range(start, end)
                            ),
                        }
                    )
    return hits


def pdf_render(path: Path, spec: str, dpi: int = 150) -> list[tuple[int, bytes]]:
    images = []
    with open_pdf(path) as document:
        for number in page_numbers(spec, len(document))[:6]:
            with closing(document[number - 1]) as page:
                bitmap = page.render(scale=dpi / 72)
                try:
                    with bitmap.to_pil() as image:
                        buffer = io.BytesIO()
                        image.save(buffer, format="PNG")
                        images.append((number, buffer.getvalue()))
                finally:
                    bitmap.close()
    return images
