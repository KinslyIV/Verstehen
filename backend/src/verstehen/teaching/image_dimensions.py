import struct

MAX_IMAGE_PIXELS = 16_000_000
MAX_IMAGE_SIDE = 8192
DIMENSIONS_ERROR = (
    "Image exceeds 16 megapixels or 8192 pixels per side; provide a smaller image"
)


def bounded(width: int, height: int) -> tuple[int, int]:
    if width <= 0 or height <= 0:
        raise ValueError("Invalid image dimensions")
    if max(width, height) > MAX_IMAGE_SIDE or width * height > MAX_IMAGE_PIXELS:
        raise ValueError(DIMENSIONS_ERROR)
    return width, height


def gif_dimensions(data: bytes) -> tuple[int, int]:
    geometry = bounded(*struct.unpack_from("<HH", data, 6))
    packed = data[10]
    offset = 13 + (3 * (1 << ((packed & 7) + 1)) if packed & 128 else 0)

    def skip_blocks(offset: int) -> int:
        while offset < len(data):
            size = data[offset]
            offset += 1
            if not size:
                return offset
            offset += size
        raise ValueError("Incomplete GIF")

    while offset < len(data):
        tag = data[offset]
        offset += 1
        if tag == 0x3B:
            return geometry
        if tag == 0x21:
            offset = skip_blocks(offset + 1)
            continue
        if tag != 0x2C:
            break
        left, top, width, height, packed = struct.unpack_from("<HHHHB", data, offset)
        bounded(width, height)
        if left + width > geometry[0] or top + height > geometry[1]:
            break
        offset += 9 + (3 * (1 << ((packed & 7) + 1)) if packed & 128 else 0)
        offset = skip_blocks(offset + 1)
    raise ValueError("Could not read valid image dimensions")


def webp_dimensions(data: bytes) -> tuple[int, int]:
    end = struct.unpack_from("<I", data, 4)[0] + 8
    if end > len(data):
        raise ValueError("Incomplete WebP")
    geometry: tuple[int, int] | None = None

    def scan(start: int, end: int, frame: bool = False) -> None:
        nonlocal geometry
        offset = start
        while offset + 8 <= end:
            kind = data[offset : offset + 4]
            size = struct.unpack_from("<I", data, offset + 4)[0]
            start = offset + 8
            if start + size > end:
                raise ValueError("Incomplete WebP chunk")
            if kind == b"VP8X" and size >= 10:
                geometry = bounded(
                    1 + int.from_bytes(data[start + 4 : start + 7], "little"),
                    1 + int.from_bytes(data[start + 7 : start + 10], "little"),
                )
            if kind == b"VP8 " and size >= 10:
                width, height = struct.unpack_from("<HH", data, start + 6)
                dimensions = bounded(width & 0x3FFF, height & 0x3FFF)
                geometry = geometry or dimensions
            if kind == b"VP8L" and size >= 5 and data[start] == 0x2F:
                bits = struct.unpack_from("<I", data, start + 1)[0]
                dimensions = bounded((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
                geometry = geometry or dimensions
            if kind == b"ANMF":
                if frame or size < 16:
                    raise ValueError("Invalid WebP animation frame")
                bounded(
                    1 + int.from_bytes(data[start + 6 : start + 9], "little"),
                    1 + int.from_bytes(data[start + 9 : start + 12], "little"),
                )
                scan(start + 16, start + size, True)
            offset = start + size + size % 2

    scan(12, end)
    if geometry:
        return geometry
    raise ValueError("Could not read valid image dimensions")


def check_image_dimensions(data: bytes) -> tuple[int, int]:
    """Check source and animation-frame headers before allocating decoded pixels."""
    try:
        if data.startswith(b"\x89PNG"):
            return bounded(*struct.unpack_from(">II", data, 16))
        if data.startswith(b"BM"):
            header = struct.unpack_from("<I", data, 14)[0]
            if header == 12:
                return bounded(*struct.unpack_from("<HH", data, 18))
            width, height = struct.unpack_from("<ii", data, 18)
            return bounded(width, abs(height))
        if data.startswith(b"\xff\xd8"):
            offset = 2
            while offset < len(data):
                if data[offset] != 255:
                    break
                offset += 1
                while data[offset] == 255:
                    offset += 1
                marker = data[offset]
                offset += 1
                if marker in (0xDA, 0xD9):
                    break
                size = struct.unpack_from(">H", data, offset)[0]
                if size < 2 or offset + size > len(data):
                    break
                if marker in (
                    0xC0,
                    0xC1,
                    0xC2,
                    0xC3,
                    0xC5,
                    0xC6,
                    0xC7,
                    0xC9,
                    0xCA,
                    0xCB,
                    0xCD,
                    0xCE,
                    0xCF,
                ):
                    if size < 8:
                        break
                    height, width = struct.unpack_from(">HH", data, offset + 3)
                    return bounded(width, height)
                offset += size
        if data.startswith(b"GIF"):
            return gif_dimensions(data)
        if data.startswith(b"RIFF"):
            return webp_dimensions(data)
    except (struct.error, IndexError) as error:
        raise ValueError("Incomplete image header") from error
    raise ValueError("Could not read valid image dimensions")
