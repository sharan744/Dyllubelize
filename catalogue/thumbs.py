"""Small, fast-loading copies of product photos for the mobile app.

Phones on a weak connection were downloading every full-size photo each time
the catalogue opened. The API now sends a small JPEG (max 640px, ~30-80 KB)
for lists and grids, and keeps the original for the zoom view.

Thumbnails live in MEDIA_ROOT/thumbs/. The file name contains the original's
modification time, so a replaced photo gets a NEW url and phones that cached
the old one download the new one automatically, while unchanged photos can be
cached on the phone forever.
"""
import logging
import os

from django.conf import settings

log = logging.getLogger(__name__)

THUMB_MAX = 640       # longest side in px — sharp on tablet catalogue cards
THUMB_QUALITY = 80
THUMB_DIR = "thumbs"


def _thumb_rel(image_field):
    """Relative media path of the thumbnail for this image, or None."""
    try:
        src = image_field.path
        mtime = int(os.path.getmtime(src))
    except (ValueError, NotImplementedError, OSError):
        return None
    stem, _ext = os.path.splitext(image_field.name)
    return f"{THUMB_DIR}/{stem}_{mtime}_{THUMB_MAX}.jpg"


def ensure_thumb(image_field):
    """Create the thumbnail if it doesn't exist yet. Returns its relative path
    (or None if the photo is missing / unreadable)."""
    if not image_field:
        return None
    rel = _thumb_rel(image_field)
    if rel is None:
        return None
    dest = os.path.join(settings.MEDIA_ROOT, rel)
    if os.path.exists(dest):
        return rel
    try:
        from PIL import Image

        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with Image.open(image_field.path) as im:
            try:
                im.seek(0)            # first frame of animated GIF / WebP
            except EOFError:
                pass
            im = im.convert("RGBA") if im.mode in ("P", "LA", "RGBA") else im.convert("RGB")
            im.thumbnail((THUMB_MAX, THUMB_MAX))
            if im.mode == "RGBA":     # transparent PNG -> white background
                bg = Image.new("RGB", im.size, (255, 255, 255))
                bg.paste(im, mask=im.split()[-1])
                im = bg
            tmp = dest + ".tmp"
            im.save(tmp, "JPEG", quality=THUMB_QUALITY, optimize=True, progressive=True)
            os.replace(tmp, dest)
        return rel
    except Exception:  # never break the API because of one bad photo
        log.exception("Thumbnail failed for %s", getattr(image_field, "name", "?"))
        return None


def thumb_url(request, image_field):
    """Absolute URL of the small copy; falls back to the original photo."""
    if not image_field:
        return ""
    rel = ensure_thumb(image_field)
    url = settings.MEDIA_URL.rstrip("/") + "/" + rel if rel else image_field.url
    if not url.startswith(("/", "http")):
        url = "/" + url
    return request.build_absolute_uri(url) if request else url
