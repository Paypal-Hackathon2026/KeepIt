from io import BytesIO

import pytest
from PIL import Image, UnidentifiedImageError

from app.services.images import to_jpeg


def _image_bytes(image: Image.Image, image_format: str) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format=image_format)
    return buffer.getvalue()


def test_to_jpeg_resizes_large_image_to_maximum_side():
    source = _image_bytes(Image.new("RGB", (2400, 1600), color="red"), "JPEG")

    result = Image.open(BytesIO(to_jpeg(source)))

    assert result.format == "JPEG"
    assert max(result.size) == 1280
    assert result.size == (1280, 853)


def test_to_jpeg_converts_transparent_png_to_jpeg():
    source = _image_bytes(
        Image.new("RGBA", (32, 24), color=(255, 0, 0, 100)),
        "PNG",
    )

    result = Image.open(BytesIO(to_jpeg(source)))

    assert result.format == "JPEG"
    assert result.mode == "RGB"
    assert result.size == (32, 24)


def test_to_jpeg_rejects_non_image_data():
    with pytest.raises(UnidentifiedImageError):
        to_jpeg(b"not an image")
