"""Per-image analysis: hashes, date, sharpness, exposure."""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import numpy as np
from PIL import Image, ImageOps

try:  # optional iPhone HEIC support
    from pillow_heif import register_heif_opener  # type: ignore

    register_heif_opener()
    HEIC_SUPPORTED = True
except Exception:  # pragma: no cover
    HEIC_SUPPORTED = False

Image.MAX_IMAGE_PIXELS = 300_000_000
THUMB = 56  # px, square thumbnail kept for the UI animation

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".jpe", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff",
}
if HEIC_SUPPORTED:
    IMAGE_EXTENSIONS |= {".heic", ".heif"}

EXIF_IFD = 0x8769
TAG_DATETIME_ORIGINAL = 36867
TAG_DATETIME_DIGITIZED = 36868
TAG_DATETIME = 306
TAG_MAKE = 271
TAG_MODEL = 272

# Pre-computed DCT matrix for the 32x32 perceptual hash
_N = 32
_DCT = np.array(
    [[np.sqrt((1 if k == 0 else 2) / _N) * np.cos(np.pi * (2 * n + 1) * k / (2 * _N))
      for n in range(_N)] for k in range(_N)],
    dtype=np.float64,
)

_COPY_NAME = re.compile(r"(copy|kopie|\(\d+\)|[ _-]\d{1,2}$|duplicate)", re.IGNORECASE)
_SCREENSHOT_NAME = re.compile(r"(screenshot|screen shot|screen_shot|scrnshot|capture|snip)", re.IGNORECASE)


@dataclass
class PhotoInfo:
    path: str
    size_bytes: int = 0
    width: int = 0
    height: int = 0
    sha256: str = ""
    dhash: int = 0
    phash: int = 0
    taken: Optional[datetime] = None
    date_source: str = "file"
    camera: str = ""
    sharpness: float = 0.0
    brightness: float = 0.0
    contrast: float = 0.0
    error: str = ""
    # filled later
    score: float = 0.0
    category: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.error

    @property
    def megapixels(self) -> float:
        return self.width * self.height / 1_000_000

    @property
    def name(self) -> str:
        return os.path.basename(self.path)

    @property
    def looks_like_copy(self) -> bool:
        stem = os.path.splitext(self.name)[0]
        return bool(_COPY_NAME.search(stem))

    @property
    def looks_like_screenshot(self) -> bool:
        if _SCREENSHOT_NAME.search(self.name):
            return True
        # PNG with no camera info and a typical screen aspect ratio
        if self.path.lower().endswith(".png") and not self.camera and self.width and self.height:
            ratio = max(self.width, self.height) / min(self.width, self.height)
            screen_ratios = (16 / 9, 16 / 10, 4 / 3, 19.5 / 9, 20 / 9, 18 / 9, 3 / 2, 21 / 9)
            return any(abs(ratio - r) < 0.03 for r in screen_ratios)
        return False


def _parse_exif_date(value) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, bytes):
        value = value.decode(errors="ignore")
    value = str(value).strip().replace("\x00", "")
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y:%m:%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(value[:19], fmt)
            if 1990 <= dt.year <= datetime.now().year + 1:
                return dt
        except ValueError:
            continue
    return None


_NAME_DATE = re.compile(r"(20\d{2}|19\d{2})[-_.]?(0[1-9]|1[0-2])[-_.]?(0[1-9]|[12]\d|3[01])")


def _date_from_name(name: str) -> Optional[datetime]:
    """WhatsApp/Android style names like IMG-20240512-WA0003.jpg or 20240512_101500.jpg."""
    m = _NAME_DATE.search(name)
    if not m:
        return None
    try:
        dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if dt <= datetime.now():
            return dt
    except ValueError:
        pass
    return None


def _bits_to_int(bits: np.ndarray) -> int:
    value = 0
    for b in bits.flatten():
        value = (value << 1) | int(b)
    return value


def _laplacian_variance(gray: np.ndarray) -> float:
    g = gray.astype(np.float32)
    lap = (-4 * g[1:-1, 1:-1] + g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:])
    return float(lap.var())


def analyze(path: str) -> PhotoInfo:
    info = PhotoInfo(path=path)
    try:
        st = os.stat(path)
        info.size_bytes = st.st_size
        with open(path, "rb") as fh:
            data = fh.read()
        info.sha256 = hashlib.sha256(data).hexdigest()

        with Image.open(path) as im:
            info.width, info.height = im.size

            # --- metadata -------------------------------------------------
            try:
                exif = im.getexif()
                sub = exif.get_ifd(EXIF_IFD) if exif else {}
                dt = (_parse_exif_date(sub.get(TAG_DATETIME_ORIGINAL))
                      or _parse_exif_date(sub.get(TAG_DATETIME_DIGITIZED))
                      or _parse_exif_date(exif.get(TAG_DATETIME)))
                if dt:
                    info.taken, info.date_source = dt, "exif"
                make = str(exif.get(TAG_MAKE, "") or "").strip("\x00 ")
                model = str(exif.get(TAG_MODEL, "") or "").strip("\x00 ")
                info.camera = f"{make} {model}".strip()
            except Exception:
                exif = None

            # --- pixels ---------------------------------------------------
            if getattr(im, "is_animated", False):
                im.seek(0)
            try:
                im.draft("RGB", (1024, 1024))  # fast JPEG decode at reduced size
            except Exception:
                pass
            im = ImageOps.exif_transpose(im)
            if im.mode in ("RGBA", "LA", "P"):
                im = im.convert("RGBA")
                bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
                im = Image.alpha_composite(bg, im)
            rgb = im.convert("RGB")
            gray = rgb.convert("L")
            # small square thumbnail for the animated mosaic in the UI
            th = ImageOps.fit(rgb, (THUMB, THUMB), Image.Resampling.BILINEAR)
            info.extra["thumb"] = th.tobytes()

        # orientation-corrected dimensions (keep real pixel count)
        if gray.size[0] < gray.size[1] and info.width > info.height:
            info.width, info.height = info.height, info.width

        g512 = gray.copy()
        g512.thumbnail((512, 512), Image.Resampling.BILINEAR)
        arr = np.asarray(g512, dtype=np.uint8)
        info.sharpness = _laplacian_variance(arr) if min(arr.shape) > 3 else 0.0
        info.brightness = float(arr.mean())
        info.contrast = float(arr.std())

        # difference hash (9x8)
        d = np.asarray(gray.resize((9, 8), Image.Resampling.LANCZOS), dtype=np.int16)
        info.dhash = _bits_to_int(d[:, 1:] > d[:, :-1])

        # perceptual hash (DCT of 32x32, top-left 8x8)
        p = np.asarray(gray.resize((32, 32), Image.Resampling.LANCZOS), dtype=np.float64)
        dct = _DCT @ p @ _DCT.T
        low = dct[:8, :8].flatten()
        med = np.median(low[1:])
        info.phash = _bits_to_int(low > med)

        if info.taken is None:
            dt = _date_from_name(info.name)
            if dt:
                info.taken, info.date_source = dt, "filename"
            else:
                info.taken, info.date_source = datetime.fromtimestamp(st.st_mtime), "file"
    except Exception as exc:  # corrupt / unreadable
        info.error = f"{type(exc).__name__}: {exc}"
        if info.taken is None:
            try:
                info.taken = datetime.fromtimestamp(os.path.getmtime(path))
            except OSError:
                info.taken = datetime.now()
    return info
