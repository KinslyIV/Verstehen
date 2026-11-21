import asyncio
import re

from fastapi import APIRouter, HTTPException, Request
from starlette.responses import Response

from verstehen.teaching.files.access import regular_file
from verstehen.teaching.files.read import ImageAttachment

router = APIRouter()


@router.get("/api/images/{sha256}.{ext}", response_class=Response)
async def get_image(sha256: str, ext: str, request: Request) -> Response:
    if not re.fullmatch(r"[a-f0-9]{64}", sha256) or ext not in {
        "png",
        "jpeg",
        "gif",
        "webp",
    }:
        raise HTTPException(404)
    attachment = ImageAttachment(sha256=sha256, extension=ext)
    data_dir = request.app.state.data_dir

    def read() -> bytes:
        with regular_file(attachment.path(data_dir)) as stream:
            return stream.read()

    try:
        data = await asyncio.to_thread(read)
    except (OSError, ValueError) as error:
        raise HTTPException(404) from error
    return Response(
        data, media_type=f"image/{ext}", headers={"Cache-Control": "no-store"}
    )
