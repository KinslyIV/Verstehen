import asyncio
import json
import struct
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image, PngImagePlugin
from pydantic_ai.messages import ToolReturnPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

from backend.tests.session.test_turns import (
    completed,
    scripted,
    start,
    turn_service_context,
)
from backend.tests.shell.test_api import TOKEN, desktop_client
from backend.tests.teaching.test_teaching_flow import probe_assessment
from verstehen.session.projection import to_llm_messages
from verstehen.store.settings import FileAccessSettings
from verstehen.teaching.files.access import SourceAccess
from verstehen.teaching.files.read import save_attachment
from verstehen.teaching.image_dimensions import DIMENSIONS_ERROR, check_image_dimensions
from verstehen.teaching.images import (
    MAX_IMAGE_BYTES,
    SHOW_IMAGE_DESCRIPTION,
    check_learner_image,
    load_learner_image,
    show_image_tool,
)


def access_for(tmp_path: Path) -> SourceAccess:
    return SourceAccess(FileAccessSettings(), tmp_path / "data", tmp_path)


def test_missing_nonregular_unsupported_and_oversize_images_use_learnharness_texts(
    tmp_path: Path,
):
    access = access_for(tmp_path)
    with pytest.raises(
        ValueError, match=f"Cannot open image {tmp_path}/missing: no such file"
    ):
        check_learner_image("missing", access)
    with pytest.raises(ValueError, match="it is not a regular file"):
        check_learner_image(str(tmp_path), access)
    path = tmp_path / "image"
    path.write_text("not an image")
    with pytest.raises(
        ValueError, match=r"not a supported image \(jpg, png, gif, webp, or bmp\)"
    ):
        check_learner_image(str(path), access)
    with path.open("wb") as stream:
        stream.truncate(MAX_IMAGE_BYTES + 1)
    with pytest.raises(
        ValueError, match="image exceeds 25 MiB; provide a smaller image"
    ):
        check_learner_image(str(path), access)


@pytest.mark.parametrize("format", ["JPEG", "PNG", "GIF", "WEBP", "BMP"])
def test_supported_formats_become_metadata_free_png_snapshots(
    tmp_path: Path, format: str
):
    path = tmp_path / "image"
    Image.new("RGB", (60, 40), "red").save(path, format=format)
    image = asyncio.run(
        load_learner_image(str(path), access_for(tmp_path), tmp_path / "data")
    )
    assert (image.width, image.height, image.mime_type) == (60, 40, "image/png")
    assert image.path == str(path)
    with Image.open(tmp_path / "data/images" / f"{image.sha256}.png") as stored:
        assert stored.size == (60, 40)
        assert not stored.getexif()
        assert not stored.info


def test_orientation_is_applied_and_exif_and_png_metadata_are_removed(tmp_path: Path):
    path = tmp_path / "rotated.jpg"
    exif = Image.Exif()
    exif[274] = 6
    exif[315] = "private author"
    Image.new("RGB", (60, 40), "red").save(path, exif=exif)
    image = asyncio.run(
        load_learner_image(str(path), access_for(tmp_path), tmp_path / "data")
    )
    assert (image.width, image.height) == (40, 60)
    stored_path = tmp_path / "data/images" / f"{image.sha256}.png"
    with Image.open(stored_path) as stored:
        assert not stored.getexif() and not stored.info
    info = PngImagePlugin.PngInfo()
    info.add_text("private", "private comment")
    path = tmp_path / "metadata.png"
    Image.new("RGBA", (3, 2), (255, 0, 0, 100)).save(path, pnginfo=info)
    image = asyncio.run(
        load_learner_image(str(path), access_for(tmp_path), tmp_path / "data")
    )
    with Image.open(tmp_path / "data/images" / f"{image.sha256}.png") as stored:
        assert not stored.info
        assert stored.getpixel((0, 0)) == (255, 0, 0, 100)


@pytest.mark.parametrize("size", [(8193, 1), (4001, 4000), (100000, 100000)])
def test_source_geometry_is_rejected_before_decode(
    tmp_path: Path, size: tuple[int, int]
):
    path = tmp_path / "large.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR" + struct.pack(">II", *size))
    with pytest.raises(ValueError, match=DIMENSIONS_ERROR):
        asyncio.run(
            load_learner_image(str(path), access_for(tmp_path), tmp_path / "data")
        )


def test_exact_geometry_limits_are_allowed_and_large_images_shrink(tmp_path: Path):
    header = b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR"
    assert check_image_dimensions(header + struct.pack(">II", 8192, 1)) == (8192, 1)
    assert check_image_dimensions(header + struct.pack(">II", 4000, 4000)) == (
        4000,
        4000,
    )
    path = tmp_path / "wide.png"
    Image.new("RGB", (3200, 1600)).save(path)
    image = asyncio.run(
        load_learner_image(str(path), access_for(tmp_path), tmp_path / "data")
    )
    assert (image.width, image.height) == (1600, 800)


def test_animated_png_is_unsupported(tmp_path: Path):
    path = tmp_path / "animated.png"
    Image.new("RGB", (3, 2), "red").save(
        path, save_all=True, append_images=[Image.new("RGB", (3, 2), "blue")]
    )
    with pytest.raises(ValueError, match="not a supported image"):
        check_learner_image(str(path), access_for(tmp_path))


@pytest.mark.parametrize("format", ["GIF", "WEBP"])
def test_animation_normalizes_the_first_frame(tmp_path: Path, format: str):
    path = tmp_path / "animated"
    Image.new("RGB", (3, 2), "red").save(
        path,
        format=format,
        save_all=True,
        append_images=[Image.new("RGB", (3, 2), "blue")],
        lossless=True,
    )
    image = asyncio.run(
        load_learner_image(str(path), access_for(tmp_path), tmp_path / "data")
    )
    with Image.open(tmp_path / "data/images" / f"{image.sha256}.png") as stored:
        pixel = stored.getpixel((0, 0))
        assert isinstance(pixel, tuple) and pixel[:3] == (255, 0, 0)
        assert not getattr(stored, "is_animated", False)


def test_protected_and_canonical_escape_paths_are_refused(tmp_path: Path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    path = tmp_path / "outside.png"
    Image.new("RGB", (3, 2)).save(path)
    (allowed / "escape.png").symlink_to(path)
    access = SourceAccess(
        FileAccessSettings(restricted=True, folders=[str(allowed)]),
        tmp_path / "data",
        tmp_path,
    )
    with pytest.raises(ValueError, match="outside the allowed folders"):
        asyncio.run(
            load_learner_image(str(allowed / "escape.png"), access, tmp_path / "data")
        )
    with pytest.raises(ValueError, match="protected location"):
        check_learner_image(".env", access)


def test_show_image_schema_and_teacher_only_wiring_and_text_only_replay(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setenv("HOME", str(tmp_path))

    async def scenario():
        path = tmp_path / "figure.png"
        Image.new("RGB", (3, 2)).save(path)
        requests = 0

        async def stream(messages: list, info: AgentInfo):
            nonlocal requests
            requests += 1
            assert "show_image" in {tool.name for tool in info.function_tools}
            if requests == 1:
                yield {
                    0: DeltaToolCall(
                        name="show_image",
                        json_args=json.dumps(
                            {"path": str(path), "caption": "  A figure  "}
                        ),
                        tool_call_id="image",
                    )
                }
            else:
                returned = next(
                    part
                    for part in messages[-1].parts
                    if isinstance(part, ToolReturnPart)
                )
                assert returned.content == f"Shown to the learner: {path} (3×2)."
                yield "Here is your figure."

        async with turn_service_context(
            tmp_path, FunctionModel(stream_function=stream)
        ) as (service, session_id):
            tool = show_image_tool(service.settings_store, tmp_path)
            assert tool.description == SHOW_IMAGE_DESCRIPTION
            assert tool.function_schema.json_schema == {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Path to the learner's image file (relative or absolute)",
                    },
                    "caption": {
                        "type": "string",
                        "description": "One short line shown under the image",
                    },
                },
                "required": ["path"],
            }
            await service.entries_store.append(session_id, probe_assessment())
            await completed(await start(service, session_id))
            entries = await service.entries_store.list(session_id)
            result = next(
                entry
                for entry in entries
                if entry.kind == "tool_result" and entry.tool_name == "show_image"
            )
            assert isinstance(result.details, dict)
            assert result.details == {
                "path": str(path),
                "caption": "A figure",
                "mime_type": "image/png",
                "sha256": result.details["sha256"],
                "width": 3,
                "height": 2,
            }
            for message in to_llm_messages(entries, data_dir=tmp_path):
                for part in message.parts:
                    if (
                        isinstance(part, ToolReturnPart)
                        and part.tool_name == "show_image"
                    ):
                        assert part.content == result.text

        async def prober_stream(messages: list, info: AgentInfo):
            assert "show_image" not in {tool.name for tool in info.function_tools}
            yield "Probing."

        (tmp_path / "prober").mkdir()
        async with turn_service_context(
            tmp_path / "prober", FunctionModel(stream_function=prober_stream)
        ) as (service, session_id):
            await completed(await start(service, session_id))

    asyncio.run(scenario())


def test_fake_model_can_call_show_image_and_blank_caption_is_omitted(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setenv("HOME", str(tmp_path))

    async def scenario():
        path = tmp_path / "image.png"
        Image.new("RGB", (3, 2)).save(path)
        model = scripted(
            tmp_path,
            [
                {
                    "tool_calls": [
                        {
                            "name": "show_image",
                            "arguments": {"path": str(path), "caption": "  "},
                        }
                    ]
                },
                {"text": "Shown."},
            ],
        )
        async with turn_service_context(tmp_path, model) as (service, session_id):
            await service.entries_store.append(session_id, probe_assessment())
            await completed(await start(service, session_id))
            entries = await service.entries_store.list(session_id)
            result = next(
                entry
                for entry in entries
                if entry.kind == "tool_result" and entry.tool_name == "show_image"
            )
            assert not result.is_error
            assert isinstance(result.details, dict) and "caption" not in result.details

    asyncio.run(scenario())


def test_image_route_requires_token_and_serves_only_stored_hashes(tmp_path: Path):
    output = BytesIO()
    Image.new("RGB", (3, 2)).save(output, format="PNG")
    data = output.getvalue()
    image = save_attachment(data, "png", tmp_path)
    path = f"/api/images/{image.sha256}.png"
    with desktop_client(tmp_path) as client:
        assert client.get(path).status_code == 403
        assert (
            client.get(path, headers={"x-verstehen-token": "wrong"}).status_code == 403
        )
        headers = {"x-verstehen-token": TOKEN}
        response = client.get(path, headers=headers)
        assert response.status_code == 200
        assert response.content == data
        assert response.headers["content-type"] == "image/png"
        for invalid in (
            "figure.png",
            f"{image.sha256}.svg",
            f"{'0' * 64}.png",
            f"{image.sha256}.jpeg",
        ):
            assert (
                client.get(f"/api/images/{invalid}", headers=headers).status_code == 404
            )
        target = tmp_path / "outside.png"
        target.write_bytes(data)
        image.path(tmp_path).unlink()
        image.path(tmp_path).symlink_to(target)
        assert client.get(path, headers=headers).status_code == 404


@pytest.mark.parametrize("format", ["JPEG", "BMP", "GIF", "WEBP"])
def test_each_format_checks_source_geometry_before_decode(format: str):
    output = BytesIO()
    Image.new("RGB", (2, 2)).save(output, format=format, lossless=True)
    data = bytearray(output.getvalue())
    if format == "JPEG":
        marker = data.index(b"\xff\xc0")
        struct.pack_into(">HH", data, marker + 5, 1, 8193)
    elif format == "BMP":
        struct.pack_into("<ii", data, 18, 8193, 1)
    elif format == "GIF":
        struct.pack_into("<HH", data, 6, 8193, 1)
    else:
        marker = data.index(b"VP8L")
        struct.pack_into("<I", data, marker + 9, 8192)
    with pytest.raises(ValueError, match=DIMENSIONS_ERROR):
        check_image_dimensions(bytes(data))


def test_gif_frame_outside_canvas_is_rejected_before_decode():
    output = BytesIO()
    Image.new("RGB", (2, 2)).save(output, format="GIF")
    data = bytearray(output.getvalue())
    packed = data[10]
    frame = 13 + (3 * (1 << ((packed & 7) + 1)) if packed & 128 else 0)
    assert data[frame] == 0x2C
    struct.pack_into("<HH", data, frame + 5, 8193, 1)
    with pytest.raises(ValueError, match=DIMENSIONS_ERROR):
        check_image_dimensions(bytes(data))


def test_webp_animation_frame_limit_is_checked_before_decode():
    canvas = b"VP8X" + struct.pack("<I", 10) + b"\0" * 10
    frame = b"\0" * 6 + (8192).to_bytes(3, "little") + b"\0" * 7
    chunks = canvas + b"ANMF" + struct.pack("<I", len(frame)) + frame
    data = b"RIFF" + struct.pack("<I", len(chunks) + 4) + b"WEBP" + chunks
    with pytest.raises(ValueError, match=DIMENSIONS_ERROR):
        check_image_dimensions(data)


def test_exact_byte_limit_passes_the_preflight_check(tmp_path: Path):
    path = tmp_path / "image.png"
    Image.new("RGB", (3, 2)).save(path)
    with path.open("r+b") as stream:
        stream.truncate(MAX_IMAGE_BYTES)
    assert check_learner_image(str(path), access_for(tmp_path)) == path


def test_noisy_snapshot_fits_learnharness_embedded_size_limit(tmp_path: Path):
    path = tmp_path / "noise.png"
    Image.effect_noise((1600, 1600), 100).convert("RGB").save(path)
    image = asyncio.run(
        load_learner_image(str(path), access_for(tmp_path), tmp_path / "data")
    )
    assert image.mime_type == "image/jpeg"
    data = (tmp_path / "data/images" / f"{image.sha256}.jpeg").read_bytes()
    assert ((len(data) + 2) // 3) * 4 < 1024 * 1024
    assert max(image.width, image.height) <= 1600
