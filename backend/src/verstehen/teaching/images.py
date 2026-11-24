import asyncio
import os
import stat
from io import BytesIO
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, Field
from pydantic_ai import Tool
from pydantic_ai.exceptions import ToolFailed
from pydantic_ai.tools import ToolReturn
lazy from PIL import Image, ImageOps, UnidentifiedImageError

from verstehen.store.settings import SettingsStore
from verstehen.teaching.files.access import SourceAccess, regular_file
from verstehen.teaching.files.read import save_attachment
from verstehen.teaching.image_dimensions import bounded, check_image_dimensions
from verstehen.teaching.tool_schema import TeachingToolSchema

MAX_IMAGE_BYTES = 25 * 1024 * 1024
SHOW_IMAGE_DESCRIPTION = (
    "Show one of the learner's image files (jpg, png, gif, webp, bmp) in the lesson as-is, with an optional caption. "
    "Instant. The result only confirms what was shown — the image is not sent back to you; use read to look at it. "
    "To draw marks on the image, call visual with its path instead. Visual results display automatically: do not repeat a newly delivered result. "
    "Show a picture again only when resurfacing it meaningfully helps the current explanation. Local paths follow File access settings; use ls to discover allowed folders."
)


class LearnerImage(BaseModel):
    path: str
    mime_type: Literal["image/png", "image/jpeg"]
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    width: int
    height: int


def supported_image(data: bytes) -> bool:
    if data.startswith(b"\xff\xd8\xff"):
        return data[3:4] != b"\xf7"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        if data[8:16] != b"\0\0\0\rIHDR":
            return False
        offset = 8
        while offset + 8 <= len(data):
            kind = data[offset + 4 : offset + 8]
            if kind == b"acTL":
                return False
            if kind == b"IDAT":
                break
            offset += 12 + int.from_bytes(data[offset : offset + 4], "big")
        return True
    if data.startswith((b"GIF87a", b"GIF89a")):
        return True
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return True
    if not data.startswith(b"BM") or len(data) < 26:
        return False
    size = int.from_bytes(data[2:6], "little")
    pixels = int.from_bytes(data[10:14], "little")
    header = int.from_bytes(data[14:18], "little")
    if (size and size < 26) or pixels < 14 + header or (size and pixels >= size):
        return False
    start = 22 if header == 12 else 26
    if header != 12 and not (40 <= header <= 124 and len(data) >= 30):
        return False
    return int.from_bytes(data[start : start + 2], "little") == 1 and int.from_bytes(
        data[start + 2 : start + 4], "little"
    ) in (1, 4, 8, 16, 24, 32)


def check_learner_image(path: str, access: SourceAccess) -> Path:
    absolute = access.resolve(path)
    try:
        info = absolute.stat()
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("it is not a regular file")
        if info.st_size > MAX_IMAGE_BYTES:
            raise ValueError("image exceeds 25 MiB; provide a smaller image")
        with regular_file(absolute) as stream:
            if not supported_image(stream.read(4100)):
                raise ValueError("not a supported image (jpg, png, gif, webp, or bmp)")
    except (OSError, ValueError) as error:
        reason = "no such file" if isinstance(error, FileNotFoundError) else str(error)
        raise ValueError(f"Cannot open image {absolute}: {reason}") from error
    return absolute


def normalize_image(data: bytes) -> tuple[bytes, Literal["png", "jpeg"], int, int]:
    check_image_dimensions(data)
    try:
        with Image.open(
            BytesIO(data), formats=["JPEG", "PNG", "GIF", "WEBP", "BMP"]
        ) as source:
            bounded(*source.size)
            oriented = ImageOps.exif_transpose(source)
            image = oriented.convert("RGBA")
            image.info.clear()
    except (UnidentifiedImageError, OSError) as error:
        raise ValueError("Could not decode image") from error
    image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
    while True:
        for extension, quality in (
            ("png", 80),
            ("jpeg", 80),
            ("jpeg", 85),
            ("jpeg", 70),
            ("jpeg", 55),
            ("jpeg", 40),
        ):
            output = BytesIO()
            candidate = image if extension == "png" else image.convert("RGB")
            candidate.save(output, format=extension.upper(), quality=quality)
            stored = output.getvalue()
            if ((len(stored) + 2) // 3) * 4 < 1024 * 1024:
                return stored, extension, *image.size
        if image.size == (1, 1):
            raise ValueError("Could not shrink image to an embeddable size")
        image = image.resize(
            tuple(max(1, int(side * 0.75)) for side in image.size),
            Image.Resampling.LANCZOS,
        )


async def load_learner_image(
    path: str, access: SourceAccess, data_dir: Path
) -> LearnerImage:
    def load() -> LearnerImage:
        absolute = check_learner_image(path, access)
        with regular_file(absolute) as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError("Image is not a regular file")
            data = stream.read(MAX_IMAGE_BYTES + 1)
        if len(data) > MAX_IMAGE_BYTES:
            raise ValueError("Image exceeds 25 MiB; provide a smaller image")
        if not supported_image(data):
            raise ValueError(f"Not a supported image: {absolute}")
        stored, extension, width, height = normalize_image(data)
        attachment = save_attachment(stored, extension, data_dir)
        return LearnerImage(
            path=str(absolute),
            mime_type="image/png" if extension == "png" else "image/jpeg",
            sha256=attachment.sha256,
            width=width,
            height=height,
        )

    return await asyncio.to_thread(load)


def show_image_tool(settings_store: SettingsStore, data_dir: Path) -> Tool[None]:
    async def show_image(
        path: Annotated[
            str,
            Field(
                min_length=1,
                description="Path to the learner's image file (relative or absolute)",
            ),
        ],
        caption: Annotated[
            str, Field(description="One short line shown under the image")
        ] = "",
    ) -> ToolReturn[str]:
        try:
            settings = await settings_store.read_file_access()
            access = await asyncio.to_thread(
                SourceAccess, settings, data_dir, Path.home()
            )
            image = await load_learner_image(path, access, data_dir)
        except (OSError, ValueError) as error:
            raise ToolFailed(str(error)) from error
        details = image.model_dump(mode="json")
        if caption.strip():
            details["caption"] = caption.strip()
        return ToolReturn(
            f"Shown to the learner: {image.path} ({image.width}×{image.height}).",
            metadata=details,
        )

    return Tool(
        show_image,
        description=SHOW_IMAGE_DESCRIPTION,
        schema_generator=TeachingToolSchema,
    )
