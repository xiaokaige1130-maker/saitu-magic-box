from __future__ import annotations

import hashlib
import math
import os
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageChops, ImageFilter, ImageOps, ImageStat, UnidentifiedImageError

from .db import THUMBS_DIR, connect, init_db


SUPPORTED_EXTS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
    ".webp",
    ".tif",
    ".tiff",
    ".heic",
    ".heif",
    ".cr2",
    ".cr3",
    ".nef",
    ".arw",
    ".raf",
    ".dng",
}
RAW_EXTS = {".cr2", ".cr3", ".nef", ".arw", ".raf", ".dng"}
COPY_PATTERNS = [
    re.compile(r"\s*\(\d+\)"),
    re.compile(r"\s*拷贝\s*\d*"),
    re.compile(r"\s*副本\s*\d*"),
    re.compile(r"_\d+$"),
    re.compile(r"\s+copy\s*\d*$", re.IGNORECASE),
]
EMPTY_SCENE_WORDS = ("空镜", "环境", "场布", "布置", "场景", "venue", "scene", "detail")
TAG_ORDER = ["组内最佳", "重复", "严重模糊", "模糊", "过曝", "欠曝", "低反差", "低饱和", "空镜", "推荐"]


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


def open_source_image(path: Path) -> Image.Image:
    try:
        with Image.open(path) as raw:
            return ImageOps.exif_transpose(raw).convert("RGB")
    except (OSError, UnidentifiedImageError):
        if path.suffix.lower() not in RAW_EXTS:
            raise
        try:
            import rawpy  # type: ignore[import-not-found]
        except ImportError as exc:
            raise UnidentifiedImageError("RAW support requires installing rawpy") from exc
        with rawpy.imread(str(path)) as raw:
            rgb = raw.postprocess(use_camera_wb=True, no_auto_bright=False, output_bps=8)
        return Image.fromarray(rgb).convert("RGB")


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


def image_metrics(image: Image.Image) -> dict[str, float]:
    sample = ImageOps.contain(image.convert("RGB"), (512, 512), Image.Resampling.LANCZOS)
    gray = ImageOps.grayscale(sample)
    gray_stat = ImageStat.Stat(gray)
    hsv = sample.convert("HSV")
    saturation = ImageStat.Stat(hsv.split()[1]).mean[0]
    edges = gray.filter(ImageFilter.FIND_EDGES)
    blur = round(float(ImageStat.Stat(edges).var[0]), 2)
    return {
        "brightness": round(float(gray_stat.mean[0]), 2),
        "contrast": round(float(gray_stat.stddev[0]), 2),
        "saturation": round(float(saturation), 2),
        "blur_score": blur,
    }


def quality_score(width: int, height: int, metrics: dict[str, float]) -> float:
    megapixels = (width * height) / 1_000_000
    blur = metrics["blur_score"]
    brightness = metrics["brightness"]
    contrast = metrics["contrast"]
    saturation = metrics["saturation"]
    exposure_penalty = abs(brightness - 128) * 0.22
    score = (
        min(math.log1p(max(blur, 0)) * 18, 120)
        + min(megapixels, 24) * 3
        + min(contrast, 70) * 0.75
        + min(saturation, 90) * 0.18
        - exposure_penalty
    )
    return round(max(score, 1), 2)


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
    if ext.lower() in RAW_EXTS:
        return "raw_photo"
    if ext.lower() in {".tif", ".tiff"}:
        return "tiff_photo"
    if ext.lower() == ".bmp":
        return "legacy_format"
    if ext.lower() == ".png":
        return "png_asset"
    return "photo"


def make_thumbnail_bytes(image: Image.Image) -> bytes:
    thumb = ImageOps.contain(image.convert("RGB"), (480, 480), Image.Resampling.LANCZOS)
    output = BytesIO()
    thumb.save(output, "JPEG", quality=88)
    return output.getvalue()


def base_review(name: str, metrics: dict[str, float], score: float) -> tuple[str, set[str], int]:
    tags: set[str] = set()
    lower_name = name.lower()
    if any(word in lower_name for word in EMPTY_SCENE_WORDS):
        tags.add("空镜")

    if metrics["blur_score"] < 70:
        tags.add("严重模糊")
    elif metrics["blur_score"] < 150:
        tags.add("模糊")
    if metrics["brightness"] > 235 or (metrics["brightness"] > 222 and metrics["contrast"] < 22):
        tags.add("过曝")
    elif metrics["brightness"] < 38:
        tags.add("欠曝")
    if metrics["contrast"] < 12:
        tags.add("低反差")
    if metrics["saturation"] < 18:
        tags.add("低饱和")

    quality_tags = tags - {"空镜", "低饱和"}
    if "空镜" in tags:
        status = "empty"
    elif "严重模糊" in tags or (("过曝" in tags or "欠曝" in tags) and score < 72):
        status = "waste"
    elif quality_tags:
        status = "weak"
    else:
        status = "selected"
        tags.add("推荐")

    if score >= 138 and status == "selected":
        stars = 5
    elif score >= 108 and status in {"selected", "empty"}:
        stars = 4
    elif score >= 78 and status != "waste":
        stars = 3
    elif score >= 48:
        stars = 2
    else:
        stars = 1
    return status, tags, stars


def sorted_tags(tags: set[str]) -> str:
    ordered = [tag for tag in TAG_ORDER if tag in tags]
    ordered.extend(sorted(tag for tag in tags if tag not in TAG_ORDER))
    return ",".join(ordered)


def process_image(path: Path) -> dict[str, object]:
    digest = sha256_file(path)
    image = open_source_image(path)
    foreground = crop_foreground(image)
    width, height = image.size
    metrics = image_metrics(image)
    score = quality_score(width, height, metrics)
    review_status, tags, star_rating = base_review(path.name, metrics, score)
    return {
        "path": str(path),
        "name": path.name,
        "ext": path.suffix.lower(),
        "size_bytes": path.stat().st_size,
        "width": width,
        "height": height,
        "sha256": digest,
        "dhash": dhash(foreground),
        "blur_score": metrics["blur_score"],
        "brightness": metrics["brightness"],
        "contrast": metrics["contrast"],
        "saturation": metrics["saturation"],
        "quality_score": score,
        "category": classify_name(path.name, path.suffix),
        "review_status": review_status,
        "tags": tags,
        "star_rating": star_rating,
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
    exact_groups = [items for items in exact_map.values() if len(items) > 1]
    for group_no, indexes in enumerate(exact_groups, start=1):
        for index in indexes:
            exact_group_by_index[index] = f"E{group_no:04d}"

    name_group_by_index: dict[int, str] = {}
    name_groups = [items for items in name_map.values() if len(items) > 1]
    for group_no, indexes in enumerate(name_groups, start=1):
        for index in indexes:
            name_group_by_index[index] = f"N{group_no:04d}"

    similar_group_by_index = build_similar_groups(rows, threshold=similar_threshold)
    apply_duplicate_review(rows, exact_groups, "exact")
    apply_duplicate_review(rows, name_groups, "name")
    similar_groups = invert_groups(similar_group_by_index)
    apply_duplicate_review(rows, list(similar_groups.values()), "similar")

    with connect() as conn:
        conn.execute("DELETE FROM images")
        for thumb_file in THUMBS_DIR.glob("*.jpg"):
            thumb_file.unlink(missing_ok=True)
        for index, row in enumerate(rows):
            cursor = conn.execute(
                """
                INSERT INTO images (
                    path, name, ext, size_bytes, width, height, sha256, dhash,
                    blur_score, brightness, contrast, saturation, quality_score,
                    category, review_status, tags, star_rating, exact_group, name_group, similar_group
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    row["brightness"],
                    row["contrast"],
                    row["saturation"],
                    row["quality_score"],
                    row["category"],
                    row["review_status"],
                    sorted_tags(row["tags"]),  # type: ignore[arg-type]
                    row["star_rating"],
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


def apply_duplicate_review(rows: list[dict[str, object]], groups: list[list[int]], group_type: str) -> None:
    for indexes in groups:
        if len(indexes) < 2:
            continue
        keeper = max(indexes, key=lambda item: (float(rows[item]["quality_score"]), int(rows[item]["size_bytes"])))
        for index in indexes:
            tags = rows[index]["tags"]
            if not isinstance(tags, set):
                continue
            if index == keeper:
                tags.add("组内最佳")
                if rows[index]["review_status"] == "waste" and group_type != "exact":
                    rows[index]["review_status"] = "weak"
                continue
            tags.add("重复")
            rows[index]["review_status"] = "waste"
            rows[index]["star_rating"] = min(int(rows[index]["star_rating"]), 2)


def invert_groups(mapping: dict[int, str]) -> dict[str, list[int]]:
    groups: dict[str, list[int]] = defaultdict(list)
    for index, group_id in mapping.items():
        groups[group_id].append(index)
    return dict(groups)


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
