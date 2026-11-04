from io import BytesIO
from PIL import Image, ImageOps

MAX_SIDE = 1280

def to_jpeg(data: bytes) -> bytes:
    img = Image.open(BytesIO(data))
    img.draft("RGB", (MAX_SIDE, MAX_SIDE))
    img = ImageOps.exif_transpose(img)
    img = img.convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    out = BytesIO()
    img.save(out, format="JPEG", quality=80)
    return out.getvalue()