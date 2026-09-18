"""
Every uploaded file is untrusted (brief section 28). This validator is
used by any form/view that accepts an image upload (gallery, hero, page
blocks, events). It does not just check the file extension — it opens
the file with Pillow, which parses the actual image data, so a
renamed-but-not-really-an-image payload gets rejected at decode time
rather than trusted based on its filename.
"""
from django.core.exceptions import ValidationError

MAX_UPLOAD_BYTES = 8 * 1024 * 1024  # 8 MB
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_DIMENSION = 6000  # px, guards against decompression-bomb-style images


def validate_image_upload(uploaded_file):
    if uploaded_file.size > MAX_UPLOAD_BYTES:
        raise ValidationError(f"Image must be smaller than {MAX_UPLOAD_BYTES // (1024*1024)}MB.")

    content_type = getattr(uploaded_file, "content_type", "")
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise ValidationError("Unsupported file type. Use JPEG, PNG, WebP, or GIF.")

    try:
        from PIL import Image

        uploaded_file.seek(0)
        img = Image.open(uploaded_file)
        img.verify()  # raises if not a genuine, decodable image
        uploaded_file.seek(0)
        img = Image.open(uploaded_file)  # re-open: verify() leaves the file unusable for further reads
        width, height = img.size
        if width > MAX_DIMENSION or height > MAX_DIMENSION:
            raise ValidationError(f"Image dimensions must not exceed {MAX_DIMENSION}px.")
        img_format = (img.format or "").upper()
        if img_format not in ("JPEG", "PNG", "WEBP", "GIF"):
            raise ValidationError("Unsupported or unrecognized image format.")
    except ValidationError:
        raise
    except Exception:
        raise ValidationError("This file could not be read as a valid image.")
    finally:
        uploaded_file.seek(0)

    return uploaded_file
