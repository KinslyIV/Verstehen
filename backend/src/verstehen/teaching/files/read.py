import os
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import monotonic
from typing import BinaryIO

from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field, ValidationError
from pydantic_ai.messages import BinaryContent
from pydantic_ai.tools import ToolReturn

from verstehen.teaching.files.access import regular_file
from verstehen.teaching.files.search import MAX_OUTPUT, capped

MAX_LINES = 2000
MAX_IMAGE_BASE64 = int(4.5 * 1024 * 1024)
IMAGE_FORMATS = {
    "PNG": "png",
    "JPEG": "jpeg",
    "GIF": "gif",
    "WEBP": "webp",
    "BMP": "bmp",
}


def text_slice(
    stream: BinaryIO, offset: int, limit: int | None, deadline: float
) -> str:
    selected: list[str] = []
    total = size = 0
    ends_with_newline = True
    reason = None
    for line in iter(lambda: stream.readline(MAX_OUTPUT + 1), b""):
        if monotonic() > deadline:
            raise TimeoutError(
                'Tool "read" timed out after 30s — the result was discarded'
            )
        start_of_line = ends_with_newline
        ends_with_newline = line.endswith(b"\n")
        if not start_of_line:
            continue
        total += 1
        if total < offset or reason or (limit is not None and len(selected) >= limit):
            continue
        if len(selected) == MAX_LINES:
            reason = "2000 line limit"
            continue
        text = line.removesuffix(b"\n").decode("utf-8", errors="replace")
        size += len(text.encode("utf-8")) + bool(selected)
        if size > MAX_OUTPUT:
            reason = "50.0KB limit"
        else:
            selected.append(text)
    if ends_with_newline:
        total += 1
        if total >= offset and not reason and (limit is None or len(selected) < limit):
            if len(selected) == MAX_LINES:
                reason = "2000 line limit"
            elif size + bool(selected) > MAX_OUTPUT:
                reason = "50.0KB limit"
            else:
                selected.append("")
    if total < offset:
        raise ValueError(f"Offset {offset} is beyond end of file ({total} lines total)")
    body, _ = capped(selected)
    end = offset + len(selected) - 1
    if reason:
        return f"{body}\n\n[Showing lines {offset}-{end} of {total} ({reason}). Use offset={end + 1} to continue.]"
    if end < total:
        return f"{body}\n\n[{total - end} more lines in file. Use offset={end + 1} to continue.]"
    return body


class ImageAttachment(BaseModel):
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    extension: str = Field(pattern=r"^(png|jpeg|gif|webp)$")

    def path(self, data_dir: Path) -> Path:
        return data_dir / "images" / f"{self.sha256}.{self.extension}"

    def content(self, data: bytes) -> BinaryContent:
        return BinaryContent(data=data, media_type=f"image/{self.extension}")


def fits_inline(data: bytes) -> bool:
    return ((len(data) + 2) // 3) * 4 < MAX_IMAGE_BASE64


def resize_image(image: Image.Image) -> tuple[bytes, str, str] | None:
    oriented = ImageOps.exif_transpose(image)
    width, height = oriented.size
    oriented.thumbnail((2000, 2000), Image.Resampling.LANCZOS)
    while True:
        for format, quality in (
            ("PNG", 80),
            ("JPEG", 80),
            ("JPEG", 85),
            ("JPEG", 70),
            ("JPEG", 55),
            ("JPEG", 40),
        ):
            out = BytesIO()
            candidate = oriented if format == "PNG" else oriented.convert("RGB")
            candidate.save(out, format=format, quality=quality)
            data = out.getvalue()
            if fits_inline(data):
                new_width, new_height = oriented.size
                note = ""
                if (new_width, new_height) != (width, height):
                    note = (
                        f"\n[Image: original {width}x{height}, displayed at {new_width}x{new_height}. "
                        f"Multiply coordinates by {width / new_width:.2f} to map to original image.]"
                    )
                return data, IMAGE_FORMATS[format], note
        if oriented.size == (1, 1):
            return None
        oriented = oriented.resize(
            tuple(max(1, int(dimension * 0.75)) for dimension in oriented.size),
            Image.Resampling.LANCZOS,
        )


def save_attachment(data: bytes, extension: str, data_dir: Path) -> ImageAttachment:
    attachment = ImageAttachment(sha256=sha256(data).hexdigest(), extension=extension)
    path = attachment.path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, delete_on_close=False) as temporary:
        temporary.write(data)
        temporary.close()
        os.replace(temporary.name, path)
    return attachment


def image_result(
    image: Image.Image,
    stream: BinaryIO,
    extension: str,
    data_dir: Path,
    accepts_images: bool,
) -> ToolReturn[str]:
    conversion = ""
    if extension == "bmp":
        out = BytesIO()
        try:
            image.save(out, format="PNG")
        except OSError:
            return ToolReturn(
                "Read image file [image/bmp]\n[Image omitted: could not be converted to a supported inline image format.]"
            )
        data = out.getvalue()
        extension = "png"
        conversion = "[Image converted from image/bmp to image/png.]"
    else:
        stream.seek(0)
        data = stream.read(MAX_IMAGE_BASE64)
    note = ""
    if max(image.size) > 2000 or not fits_inline(data):
        try:
            resized = resize_image(image)
        except OSError, ValueError:
            resized = None
        if resized is None:
            return ToolReturn(
                f"Read image file [image/{extension}]\n[Image omitted: could not be resized below the inline image size limit.]"
            )
        data, extension, note = resized
    text = f"Read image file [image/{extension}]"
    if conversion:
        text += f"\n{conversion}"
    text += note
    if not accepts_images:
        return ToolReturn(
            text
            + "\n[Current model does not support images. The image will be omitted from this request.]"
        )
    attachment = save_attachment(data, extension, data_dir)
    return ToolReturn(
        [text, attachment.content(data)],
        metadata={"image": attachment.model_dump(mode="json")},
    )


def read_source(
    path: Path, offset: int, limit: int | None, data_dir: Path, accepts_images: bool
) -> ToolReturn[str]:
    deadline = monotonic() + 30
    with regular_file(path) as stream:
        try:
            image = Image.open(stream, formats=list(IMAGE_FORMATS))
        except UnidentifiedImageError, OSError:
            stream.seek(0)
            text = text_slice(stream, offset, limit, deadline)
            return ToolReturn(text, metadata=text)
        with image:
            assert image.format is not None
            return image_result(
                image, stream, IMAGE_FORMATS[image.format], data_dir, accepts_images
            )


def load_attachment(details: object, data_dir: Path) -> BinaryContent | None:
    if not isinstance(details, dict) or "image" not in details:
        return None
    try:
        attachment = ImageAttachment.model_validate(details["image"])
        with regular_file(attachment.path(data_dir)) as stream:
            data = stream.read(MAX_IMAGE_BASE64)
        if not fits_inline(data) or sha256(data).hexdigest() != attachment.sha256:
            return None
        return attachment.content(data)
    except ValidationError, OSError, ValueError:
        return None
