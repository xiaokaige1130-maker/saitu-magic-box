from __future__ import annotations

import hashlib
import os
import math
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageChops, ImageFilter, ImageOps, ImageStat, UnidentifiedImageError

from .db import THUMBS_DIR, connect, init_db


SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
COPY_PATTERNS = [
    re.compile(r"\s*\(\d+\)"),
    re.compile(r"\s*拷贝\s*\d*"),
    re.compile(r"\s*副本\s*\d*"),
    re.compile(r"_\d+$"),
    re.compile(r"\s+copy\s*\d*$", re.IGNORECASE),
]


@dataclass(slots=True)
class ScanSummary:
    total: int
    exact_groups: int
    name_groups: int
    similar_groups: int
    failed: list[str]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dhash(image: Image.Image) -> str:
    gray = ImageOps.grayscale(image).resize((9, 8), Image.Resampling.LANCZOS)
    pixels = list(gray.getdata())
    bits = []
    for row in range(8):
        offset = row * 9
        for col in range(8):
            bits.append(1 if pixels[offset + col] > pixels[offset + col + 1] else 0)
    value = 0
    for bit in bits:
        value = (value << 1) | bit
    return f"{value:016x}"


def crop_foreground(image: Image.Image) -> Image.Image:
    rgb = ImageOps.contain(image.convert("RGB"), (512, 512), Image.Resampling.LANCZOS)
    background = Image.new("RGB", rgb.size, (255, 255, 255))
    diff = ImageChops.difference(rgb, background)
    mask = ImageOps.grayscale(diff).point(lambda value: 255 if value > 12 else 0)
    bbox = mask.getbbox()
    if not bbox:
        return rgb
    left, top, right, bottom = bbox
    padding = max(8, min(rgb.size) // 40)
    left = max(0, left - padding)
    top = max(0, top - padding)
    right = min(rgb.width, right + padding)
    bottom = min(rgb.height, bottom + padding)
    return rgb.crop((left, top, right, bottom))


def hamming_hex(a: str, b: str) -> int:
    return (int(a or "0", 16) ^ int(b or "0", 16)).bit_count()


def blur_score(image: Image.Image) -> float:
    gray = ImageOps.grayscale(image).resize((256, 256), Image.Resampling.LANCZOS)
    edges = gray.filter(ImageFilter.FIND_EDGES)
    return round(float(ImageStat.Stat(edges).var[0]), 2)


def quality_score(width: int, height: int, blur: float) -> float:
    megapixels = (width * height) / 1_000_000
    return round((math.log1p(max(blur, 0)) * 18) + (min(megapixels, 12) * 4), 2)


def normalize_name(name: str) -> str:
    stem = Path(name).stem
    for pattern in COPY_PATTERNS:
        stem = pattern.sub("", stem)
    return re.sub(r"[\s_\-]+", "", stem).lower()


def classify_name(name: str, ext: str) -> str:
    lower = name.lower()
    if "带型号" in name or "型号" in name or "logo" in lower:
        return "with_label"
    if "详情" in name or "大集合" in name:
        return "detail"
    if "拷贝" in name or "副本" in name or re.search(r"\(\d+\)|_\d+\.", name):
        return "copy_named"
    if ext.lower() == ".bmp":
        return "legacy_format"
    if ext.lower() == ".png":
        return "png_asset"
    return "product_image"


def make_thumbnail_bytes(image: Image.Image) -> bytes:
    thumb = ImageOps.contain(image.convert("RGB"), (360, 360), Image.Resampling.LANCZOS)
    output = BytesIO()
    thumb.save(output, "JPEG", quality=86)
    return output.getvalue()


def process_image(path: Path) -> dict[str, object]:
    digest = sha256_file(path)
    with Image.open(path) as raw:
        image = ImageOps.exif_transpose(raw).convert("RGB")
        foreground = crop_foreground(image)
        width, height = image.size
        blur = blur_score(image)
        return {
            "path": str(path),
            "name": path.name,
            "ext": path.suffix.lower(),
            "size_bytes": path.stat().st_size,
            "width": width,
            "height": height,
            "sha256": digest,
            "dhash": dhash(foreground),
            "blur_score": blur,
            "quality_score": quality_score(width, height, blur),
            "category": classify_name(path.name, path.suffix),
            "_thumb": make_thumbnail_bytes(image),
        }


def scan_folder(folder: str, similar_threshold: int = 5, recursive: bool = False) -> ScanSummary:
    init_db()
    source = Path(folder).expanduser().resolve()
    if not source.exists() or not source.is_dir():
        raise ValueError(f"folder not found: {source}")

    failed: list[str] = []
    rows: list[dict[str, object]] = []
    paths = source.rglob("*") if recursive else source.iterdir()
    image_paths = [path for path in sorted(paths, key=lambda item: item.name.lower()) if path.is_file() and path.suffix.lower() in SUPPORTED_EXTS]
    max_workers = min(8, max(2, os.cpu_count() or 4))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_image, path): path for path in image_paths}
        for future in as_completed(futures):
            path = futures[future]
            try:
                rows.append(future.result())
            except (OSError, UnidentifiedImageError) as exc:
                failed.append(f"{path.name}: {exc}")
    rows.sort(key=lambda row: str(row["name"]).lower())

    exact_map: dict[str, list[int]] = defaultdict(list)
    name_map: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        exact_map[str(row["sha256"])].append(index)
        name_map[normalize_name(str(row["name"]))].append(index)

    exact_group_by_index: dict[int, str] = {}
    for group_no, indexes in enumerate([items for items in exact_map.values() if len(items) > 1], start=1):
        for index in indexes:
            exact_group_by_index[index] = f"E{group_no:04d}"

    name_group_by_index: dict[int, str] = {}
    for group_no, indexes in enumerate([items for items in name_map.values() if len(items) > 1], start=1):
        for index in indexes:
            name_group_by_index[index] = f"N{group_no:04d}"

    similar_group_by_index = build_similar_groups(rows, threshold=similar_threshold)

    with connect() as conn:
        conn.execute("DELETE FROM images")
        for thumb_file in THUMBS_DIR.glob("*.jpg"):
            thumb_file.unlink(missing_ok=True)
        for index, row in enumerate(rows):
            cursor = conn.execute(
                """
                INSERT INTO images (
                    path, name, ext, size_bytes, width, height, sha256, dhash,
                    blur_score, quality_score, category, exact_group, name_group, similar_group
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["path"],
                    row["name"],
                    row["ext"],
                    row["size_bytes"],
                    row["width"],
                    row["height"],
                    row["sha256"],
                    row["dhash"],
                    row["blur_score"],
                    row["quality_score"],
                    row["category"],
                    exact_group_by_index.get(index, ""),
                    name_group_by_index.get(index, ""),
                    similar_group_by_index.get(index, ""),
                ),
            )
            (THUMBS_DIR / f"{int(cursor.lastrowid)}.jpg").write_bytes(row["_thumb"])  # type: ignore[arg-type]

    return ScanSummary(
        total=len(rows),
        exact_groups=len({value for value in exact_group_by_index.values()}),
        name_groups=len({value for value in name_group_by_index.values()}),
        similar_groups=len({value for value in similar_group_by_index.values()}),
        failed=failed,
    )


def build_similar_groups(rows: list[dict[str, object]], threshold: int = 5) -> dict[int, str]:
    assigned: dict[int, str] = {}
    group_no = 0
    hashes = [str(row["dhash"]) for row in rows]
    for index, value in enumerate(hashes):
        if index in assigned:
            continue
        group = [index]
        for other in range(index + 1, len(hashes)):
            if other in assigned:
                continue
            aspect_a = float(rows[index]["width"]) / max(float(rows[index]["height"]), 1)
            aspect_b = float(rows[other]["width"]) / max(float(rows[other]["height"]), 1)
            if abs(aspect_a - aspect_b) > 0.18:
                continue
            if hamming_hex(value, hashes[other]) <= threshold:
                group.append(other)
        if len(group) > 1:
            group_no += 1
            group_id = f"S{group_no:04d}"
            for item in group:
                assigned[item] = group_id
    return assigned
