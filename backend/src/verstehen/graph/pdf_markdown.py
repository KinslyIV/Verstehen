import re
import unicodedata
from collections import Counter
from contextlib import closing
from dataclasses import dataclass

from pydantic import BaseModel

from verstehen.teaching.pdfium import PDFIUM_LOCK

BULLET = re.compile(r"^\s*[\u2022\u25CF\u25AA\u2013\u2014\uF0B7-]\s+")
COMPAT = re.compile(r"[\uFB00-\uFB06\uFB50-\uFDFF\uFE70-\uFEFF]+")


class PdfPage(BaseModel):
    number: int
    kind: str
    markdown: str = ""


@dataclass
class Line:
    text: str
    size: float
    x: float
    y: float
    rotated: bool


def clean(text: str) -> str:
    text = COMPAT.sub(lambda m: unicodedata.normalize("NFKC", m[0]), text)
    return re.sub(r"[\uE000-\uF8FF\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", "", text)


def scan_page(page) -> list[Line]:
    import pypdfium2.raw as raw

    lines = []
    with closing(page.get_textpage()) as text:
        chars: list[str] = []
        size = x = y = 0
        rotated = False
        previous_end = None

        def flush():
            nonlocal chars, size, rotated, previous_end
            value = " ".join(clean("".join(chars)).split())
            if value:
                lines.append(Line(value, size, x, y, rotated))
            chars, size, rotated, previous_end = [], 0, False, None

        for i in range(text.count_chars()):
            char = chr(raw.FPDFText_GetUnicode(text.raw, i))
            if char in "\r\n":
                flush()
                continue
            left, bottom, right, top = text.get_charbox(i)
            font_size = raw.FPDFText_GetFontSize(text.raw, i)
            angle = raw.FPDFText_GetCharAngle(text.raw, i)
            if chars and abs(bottom - y) > max(font_size, size, 1) * 0.8:
                flush()
            if not chars:
                x, y = left, bottom
            if (
                previous_end is not None
                and left - previous_end > font_size * 0.25
                and chars
                and not chars[-1].isspace()
                and not char.isspace()
            ):
                chars.append(" ")
            chars.append(char)
            if char.strip():
                size = max(size, font_size)
                rotated |= abs(angle) > 0.01
            previous_end = right
        flush()
    return lines


def lines_to_markdown(lines: list[Line]) -> str:
    top = max(round(line.size, 1) for line in lines)
    smaller = [line for line in lines if round(line.size, 1) < top and not line.rotated]
    weights: Counter[int] = Counter()
    for line in smaller or [line for line in lines if not line.rotated]:
        weights[round(line.size)] += len(line.text)
    body = weights.most_common(1)[0][0] if weights else 0
    ordered = sorted(
        (line for line in lines if not line.rotated), key=lambda line: -line.y
    )
    if len(ordered) > 1:
        first, second = ordered[:2]
        i = lines.index(first)
        if (
            i > 0
            and first.size >= body + 1.95
            and first.y - second.y >= first.size * 0.8
        ):
            j = i + 1
            while (
                j < len(lines)
                and abs(lines[j].size - first.size) < 0.5
                and lines[j - 1].y - lines[j].y < first.size * 1.8
            ):
                j += 1
            lines = [*lines[i:j], *lines[:i], *lines[j:]]
    blocks = []
    list_xs = []
    last_item_y = None
    for line in lines:
        bullet = BULLET.match(line.text)
        mostly_letters = (
            sum(c.isalpha() for c in line.text) >= len(re.sub(r"\s", "", line.text)) / 2
        )
        level = (
            0
            if line.rotated
            or bullet
            or round(line.size, 1) < body + 1.95
            or not mostly_letters
            else 1
            if line.size >= body * 1.6
            else 2
            if line.size >= body * 1.3
            else 3
        )

        def plain(s: str) -> str:
            return "\\" + s if s.startswith("#") else s

        if level and len(line.text) <= 150:
            blocks.append(("#" * level + " " + line.text, False))
        elif bullet:
            indent = line.size * 0.3
            if last_item_y is not None and line.y > last_item_y + indent:
                list_xs = []
            while list_xs and line.x < list_xs[-1] - indent:
                list_xs.pop()
            if not list_xs or line.x > list_xs[-1] + indent:
                list_xs.append(line.x)
            blocks.append(
                (
                    "  " * (len(list_xs) - 1) + "- " + plain(BULLET.sub("", line.text)),
                    True,
                )
            )
            last_item_y = line.y
        else:
            blocks.append((plain(line.text), False))
    return "".join(
        value + ("\n" if item and i + 1 < len(blocks) and blocks[i + 1][1] else "\n\n")
        for i, (value, item) in enumerate(blocks)
    ).rstrip()


def convert_pdf(data: bytes, max_pages: int = 1000) -> list[PdfPage]:
    import pypdfium2 as pdfium
    import pypdfium2.raw as raw

    with PDFIUM_LOCK, pdfium.PdfDocument(data) as document:
        if len(document) > max_pages:
            raise ValueError("Too long. Max 1,000 pages.")
        pages = []
        for i in range(len(document)):
            with closing(document[i]) as page:
                lines = scan_page(page)
                if lines:
                    pages.append(
                        PdfPage(
                            number=i + 1, kind="text", markdown=lines_to_markdown(lines)
                        )
                    )
                else:
                    image = any(
                        True for _ in page.get_objects(filter=[raw.FPDF_PAGEOBJ_IMAGE])
                    )
                    pages.append(
                        PdfPage(number=i + 1, kind="image-only" if image else "empty")
                    )
        return pages


def join_pages(pages: list[PdfPage]) -> str:
    return "\n\n".join(
        f"--- Page {p.number} ---\n\n{p.markdown}" for p in pages if p.kind == "text"
    )
