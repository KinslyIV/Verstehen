import asyncio
import re

from pydantic import BaseModel

from verstehen.graph.pdf_markdown import convert_pdf, join_pages

MAX_IMPORT_BYTES = 25 * 1024 * 1024
MAX_IMPORT_BODY_BYTES = 26 * 1024 * 1024
IMPORT_EXTENSIONS = re.compile(r"\.(txt|md|markdown|rst|org|adoc|tex|pdf)$", re.I)
UNSUPPORTED_TYPE_MESSAGE = "This file type isn't supported. Use text, Markdown, or PDF."


class NotesFile(BaseModel):
    text: str
    notice: str | None = None


def valid_notes_path(path: str, filename: str) -> bool:
    parts = path.split("/")
    return (
        bool(path)
        and len(path) <= 1024
        and re.search(r"[\\:\x00-\x1f\x7f]", path) is None
        and all(part and part not in (".", "..") for part in parts)
        and (parts[-1] == filename or path == filename)
    )


async def read_notes_file(filename: str, data: bytes) -> NotesFile:
    if not IMPORT_EXTENSIONS.search(filename):
        raise ValueError(UNSUPPORTED_TYPE_MESSAGE)
    if not data.startswith(b"%PDF-"):
        if b"\0" in data[:8192]:
            raise ValueError("This file isn't plain text.")
        return NotesFile(text=data.decode("utf-8-sig", errors="replace"))
    try:
        pages = await asyncio.to_thread(convert_pdf, data)
    except ValueError:
        raise
    except Exception as error:
        raise ValueError("Could not open this PDF.") from error
    text = join_pages(pages)
    if not text:
        raise ValueError("OCR not supported yet.")
    skipped = sum(p.kind == "image-only" for p in pages)
    omission = (
        f" Skipped {skipped} image-only {'page' if skipped == 1 else 'pages'}; OCR is not supported."
        if skipped
        else ""
    )
    return NotesFile(text=text, notice="Scanned pages may have errors." + omission)
