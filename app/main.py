from __future__ import annotations

import base64
import csv
import io
import os
import shutil
import subprocess
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from .db import BASE_DIR, THUMBS_DIR, connect, init_db, row_to_dict
from .scanner import scan_folder


DEFAULT_FOLDER = r"C:\Users\云电脑\Desktop\白底图\外贸绞肉机图"
DEFAULT_OUTPUT_FOLDER = r"C:\Users\云电脑\Desktop\晒图魔方输出"

app = FastAPI(title="Image Cube", version="0.1.0")
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "app" / "static")), name="static")


class ScanRequest(BaseModel):
    folder: str = DEFAULT_FOLDER
    similar_threshold: int = 5
    recursive: bool = False


class CopyRequest(BaseModel):
    folder: str = DEFAULT_OUTPUT_FOLDER
    mode: str = "candidates"


class FolderRequest(BaseModel):
    folder: str = DEFAULT_OUTPUT_FOLDER


class PickFolderRequest(BaseModel):
    initial: str = ""
    title: str = "选择文件夹"


REASON_LABELS = {
    "exact_group": "完全相同文件",
    "name_group": "文件名副本",
    "similar_group": "视觉相似图片",
}


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "default_folder": DEFAULT_FOLDER, "default_output_folder": DEFAULT_OUTPUT_FOLDER},
    )


@app.post("/api/scan")
def scan(request: ScanRequest) -> dict[str, object]:
    try:
        summary = scan_folder(
            request.folder,
            similar_threshold=max(0, min(int(request.similar_threshold), 16)),
            recursive=request.recursive,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "total": summary.total,
        "exact_groups": summary.exact_groups,
        "name_groups": summary.name_groups,
        "similar_groups": summary.similar_groups,
        "failed": summary.failed,
    }


@app.get("/api/stats")
def stats() -> dict[str, object]:
    with connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM images").fetchone()[0]
        categories = [dict(row) for row in conn.execute("SELECT category, COUNT(*) count FROM images GROUP BY category ORDER BY count DESC")]
        exact = conn.execute("SELECT COUNT(DISTINCT exact_group) FROM images WHERE exact_group != ''").fetchone()[0]
        names = conn.execute("SELECT COUNT(DISTINCT name_group) FROM images WHERE name_group != ''").fetchone()[0]
        similar = conn.execute("SELECT COUNT(DISTINCT similar_group) FROM images WHERE similar_group != ''").fetchone()[0]
    return {"total": total, "categories": categories, "exact_groups": exact, "name_groups": names, "similar_groups": similar}


@app.get("/api/images")
def images(
    view: str = "all",
    category: str = "",
    q: str = "",
    limit: int = Query(500, ge=1, le=2000),
) -> list[dict[str, object]]:
    clauses = []
    params: list[object] = []
    if view == "exact":
        clauses.append("exact_group != ''")
    elif view == "name":
        clauses.append("name_group != ''")
    elif view == "similar":
        clauses.append("similar_group != ''")
    elif view == "weak":
        clauses.append("blur_score < 220")
    if category:
        clauses.append("category = ?")
        params.append(category)
    if q:
        clauses.append("name LIKE ?")
        params.append(f"%{q}%")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with connect() as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM images
            {where}
            ORDER BY
                CASE WHEN exact_group != '' THEN 0 ELSE 1 END,
                CASE WHEN name_group != '' THEN 0 ELSE 1 END,
                name COLLATE NOCASE
            LIMIT ?
            """,
            (*params, limit),
        ).fetchall()
    return [row_to_dict(row) for row in rows]


@app.get("/api/recommendations")
def recommendations() -> dict[str, object]:
    keepers: list[dict[str, object]] = []
    duplicate_candidates: list[dict[str, object]] = []
    seen_keeper_ids: set[int] = set()
    seen_candidate_ids: set[int] = set()
    with connect() as conn:
        for group_column in ("exact_group", "name_group", "similar_group"):
            reason_label = REASON_LABELS[group_column]
            group_ids = [
                row[0]
                for row in conn.execute(
                    f"SELECT DISTINCT {group_column} FROM images WHERE {group_column} != '' ORDER BY {group_column}"
                )
            ]
            for group_id in group_ids:
                rows = [
                    row_to_dict(row)
                    for row in conn.execute(
                        f"SELECT * FROM images WHERE {group_column} = ? ORDER BY quality_score DESC, size_bytes DESC",
                        (group_id,),
                    )
                ]
                rows = [row for row in rows if int(row["id"]) not in seen_candidate_ids]
                if len(rows) < 2:
                    continue
                reason = f"{reason_label} {group_id}"
                keeper_id = int(rows[0]["id"])
                if keeper_id not in seen_keeper_ids:
                    keepers.append({**rows[0], "reason": reason, "reason_type": group_column})
                    seen_keeper_ids.add(keeper_id)
                for row in rows[1:]:
                    image_id = int(row["id"])
                    if image_id in seen_keeper_ids or image_id in seen_candidate_ids:
                        continue
                    duplicate_candidates.append({**row, "reason": reason, "reason_type": group_column, "keeper_id": keeper_id})
                    seen_candidate_ids.add(image_id)
    return {"keepers": keepers, "duplicate_candidates": duplicate_candidates}


@app.post("/api/copy")
def copy_recommendations(request: CopyRequest) -> dict[str, object]:
    data = recommendations()
    if request.mode == "keepers":
        items = data["keepers"]
        subfolder = "保留建议"
    elif request.mode == "candidates":
        items = data["duplicate_candidates"]
        subfolder = "处理候选"
    else:
        raise HTTPException(status_code=400, detail="unknown copy mode")

    target = Path(request.folder).expanduser().resolve() / subfolder
    target.mkdir(parents=True, exist_ok=True)
    copied = 0
    for item in items:  # type: ignore[assignment]
        source = Path(str(item["path"]))
        if not source.exists():
            continue
        prefix = f"{int(item['id']):04d}_"
        shutil.copy2(source, target / f"{prefix}{source.name}")
        copied += 1
    return {"copied": copied, "target": str(target)}


@app.post("/api/open-folder")
def open_folder(request: FolderRequest) -> dict[str, object]:
    target = Path(request.folder).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    try:
        if os.name == "nt":
            os.startfile(str(target))  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(target)])
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"opened": str(target)}


@app.post("/api/pick-folder")
def pick_folder(request: PickFolderRequest) -> dict[str, object]:
    initial = request.initial if request.initial and Path(request.initial).exists() else str(Path.home())
    script = f"""
Add-Type -AssemblyName System.Windows.Forms
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = @'
{request.title}
'@
$dialog.SelectedPath = @'
{initial}
'@
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {{
    Write-Output $dialog.SelectedPath
}}
"""
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Sta", "-EncodedCommand", encoded],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=result.stderr.strip() or "folder picker failed")
    return {"folder": result.stdout.strip()}


@app.get("/api/groups/{group_type}")
def groups(group_type: str) -> list[dict[str, object]]:
    column_map = {"exact": "exact_group", "name": "name_group", "similar": "similar_group"}
    column = column_map.get(group_type)
    if not column:
        raise HTTPException(status_code=404, detail="unknown group type")
    with connect() as conn:
        group_rows = conn.execute(
            f"""
            SELECT {column} group_id, COUNT(*) count, MAX(quality_score) best_score
            FROM images
            WHERE {column} != ''
            GROUP BY {column}
            ORDER BY count DESC, group_id
            """
        ).fetchall()
        result = []
        for group in group_rows:
            image_rows = conn.execute(
                f"SELECT * FROM images WHERE {column} = ? ORDER BY quality_score DESC, size_bytes DESC",
                (group["group_id"],),
            ).fetchall()
            result.append({
                "group_id": group["group_id"],
                "count": group["count"],
                "best_score": group["best_score"],
                "reason": REASON_LABELS[column],
                "images": [row_to_dict(row) for row in image_rows],
            })
    return result


@app.get("/thumb/{image_id}")
def thumb(image_id: int) -> FileResponse:
    path = THUMBS_DIR / f"{image_id}.jpg"
    if not path.exists():
        raise HTTPException(status_code=404, detail="thumbnail not found")
    return FileResponse(path)


@app.get("/image/{image_id}")
def original(image_id: int) -> FileResponse:
    with connect() as conn:
        row = conn.execute("SELECT path FROM images WHERE id = ?", (image_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="image not found")
    path = Path(row["path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(path)


@app.get("/api/export.csv")
def export_csv() -> StreamingResponse:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "name", "path", "category", "width", "height", "size_bytes", "blur_score", "quality_score", "exact_group", "name_group", "similar_group"])
    with connect() as conn:
        for row in conn.execute("SELECT * FROM images ORDER BY name COLLATE NOCASE"):
            writer.writerow([row["id"], row["name"], row["path"], row["category"], row["width"], row["height"], row["size_bytes"], row["blur_score"], row["quality_score"], row["exact_group"], row["name_group"], row["similar_group"]])
    output.seek(0)
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=image-cube-report.csv"})
