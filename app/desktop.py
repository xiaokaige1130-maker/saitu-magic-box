from __future__ import annotations

import os
import queue
import shutil
import threading
from collections import defaultdict
from pathlib import Path
from tempfile import TemporaryDirectory
from tkinter import BooleanVar, IntVar, StringVar, filedialog, messagebox

import customtkinter as ctk
from PIL import Image

from .db import THUMBS_DIR, connect, init_db, row_to_dict
from .scanner import scan_folder


DEFAULT_FOLDER = r"C:\Users\云电脑\Desktop\白底图\外贸绞肉机图"
DEFAULT_OUTPUT_FOLDER = r"C:\Users\云电脑\Desktop\晒图魔方输出"

VIEW_LABELS = {
    "all": "全部",
    "recommend": "推荐",
    "selected": "精选",
    "weak": "较差",
    "empty": "空镜",
    "waste": "废片",
    "duplicate": "重复去重",
}
STATUS_LABELS = {
    "selected": "精选",
    "weak": "较差",
    "empty": "空镜",
    "waste": "废片",
}
STATUS_COLORS = {
    "selected": "#0f9f76",
    "weak": "#df8a22",
    "empty": "#6d5bd0",
    "waste": "#d94a4a",
}


class DesktopApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("green")
        init_db()

        self.title("筛图魔方")
        self.geometry("1320x860")
        self.minsize(1080, 720)
        self.configure(fg_color="#edf1f5")

        self.source_var = StringVar(value=DEFAULT_FOLDER)
        self.output_var = StringVar(value=DEFAULT_OUTPUT_FOLDER)
        self.threshold_var = IntVar(value=5)
        self.recursive_var = BooleanVar(value=False)
        self.search_var = StringVar(value="")
        self.view = "all"
        self.rows: list[dict[str, object]] = []
        self.checked_ids: set[int] = set()
        self.check_vars: dict[int, BooleanVar] = {}
        self.image_refs: dict[int, ctk.CTkImage] = {}
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()

        self._build_layout()
        self.load_stats()
        self.load_content()
        self.after(150, self._poll_events)

    def _build_layout(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.sidebar = ctk.CTkFrame(self, width=304, corner_radius=0, fg_color="#111827")
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)
        self.sidebar.grid_columnconfigure(0, weight=1)

        brand = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="ew", padx=18, pady=(20, 14))
        mark = ctk.CTkLabel(brand, text="筛", width=42, height=42, corner_radius=10, fg_color="#11a77a", text_color="white", font=("Microsoft YaHei UI", 18, "bold"))
        mark.pack(side="left", padx=(0, 12))
        text_box = ctk.CTkFrame(brand, fg_color="transparent")
        text_box.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(text_box, text="筛图魔方", text_color="#f8fafc", anchor="w", font=("Microsoft YaHei UI", 20, "bold")).pack(fill="x")
        ctk.CTkLabel(text_box, text="Windows 桌面筛图工具", text_color="#9ca3af", anchor="w", font=("Microsoft YaHei UI", 12)).pack(fill="x")

        settings = ctk.CTkFrame(self.sidebar, corner_radius=12, fg_color="#182235")
        settings.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 12))
        settings.grid_columnconfigure(0, weight=1)
        self._path_picker(settings, "原图文件夹", self.source_var, 0, self.pick_source)
        self._path_picker(settings, "输出文件夹", self.output_var, 2, self.pick_output)
        ctk.CTkLabel(settings, text="相似严格度", text_color="#cbd5e1", anchor="w").grid(row=4, column=0, sticky="ew", padx=12, pady=(10, 2))
        ctk.CTkSlider(settings, from_=0, to=16, variable=self.threshold_var, number_of_steps=16).grid(row=5, column=0, sticky="ew", padx=12)
        ctk.CTkSwitch(settings, text="包含子文件夹", variable=self.recursive_var, text_color="#cbd5e1").grid(row=6, column=0, sticky="w", padx=12, pady=(10, 10))
        self.scan_button = ctk.CTkButton(settings, text="开始筛选", height=40, corner_radius=8, fg_color="#11a77a", hover_color="#0d8060", command=self.scan_async)
        self.scan_button.grid(row=7, column=0, sticky="ew", padx=12, pady=(0, 12))

        self.nav_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        self.nav_frame.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 12))
        self._render_nav()

        export_frame = ctk.CTkFrame(self.sidebar, corner_radius=12, fg_color="#182235")
        export_frame.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 12))
        for column in range(2):
            export_frame.grid_columnconfigure(column, weight=1)
        actions = [
            ("全选当前", self.check_all_current),
            ("清空勾选", self.clear_checked),
            ("勾选去重", self.check_deduped_result),
            ("导出勾选", self.export_checked),
            ("去重后全部", self.export_deduped_all),
            ("导出当前", self.export_current_view),
            ("分类导出", self.export_all_categories),
            ("打开输出", self.open_output),
        ]
        for index, (text, command) in enumerate(actions):
            button = ctk.CTkButton(export_frame, text=text, height=34, corner_radius=8, fg_color="#f8fafc", hover_color="#e2e8f0", text_color="#111827", command=command)
            button.grid(row=index // 2, column=index % 2, sticky="ew", padx=(10 if index % 2 == 0 else 4, 10 if index % 2 == 1 else 4), pady=(10 if index < 2 else 4, 6))

        self.side_status = ctk.CTkLabel(self.sidebar, text="准备就绪", height=52, corner_radius=10, fg_color="#1f2a3d", text_color="#dbeafe", anchor="w", justify="left", wraplength=244, padx=12)
        self.side_status.grid(row=4, column=0, sticky="ew", padx=16, pady=(0, 12))
        self.sidebar.grid_rowconfigure(5, weight=1)

        self.main = ctk.CTkFrame(self, corner_radius=0, fg_color="#edf1f5")
        self.main.grid(row=0, column=1, sticky="nsew")
        self.main.grid_columnconfigure(0, weight=1)
        self.main.grid_rowconfigure(3, weight=1)

        header = ctk.CTkFrame(self.main, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=22, pady=(22, 12))
        header.grid_columnconfigure(0, weight=1)
        self.title_label = ctk.CTkLabel(header, text="全部", text_color="#111827", anchor="w", font=("Microsoft YaHei UI", 28, "bold"))
        self.title_label.grid(row=0, column=0, sticky="w")
        search = ctk.CTkEntry(header, textvariable=self.search_var, width=320, height=36, corner_radius=8, placeholder_text="搜索文件名")
        search.grid(row=0, column=1, sticky="e")
        search.bind("<KeyRelease>", lambda _event: self.load_content())

        self.stats_frame = ctk.CTkFrame(self.main, fg_color="transparent")
        self.stats_frame.grid(row=1, column=0, sticky="ew", padx=22, pady=(0, 8))

        self.status_label = ctk.CTkLabel(self.main, text="", text_color="#64748b", anchor="w")
        self.status_label.grid(row=2, column=0, sticky="ew", padx=22, pady=(0, 8))

        self.grid_container = ctk.CTkScrollableFrame(self.main, corner_radius=0, fg_color="#edf1f5")
        self.grid_container.grid(row=3, column=0, sticky="nsew", padx=16, pady=(0, 16))

    def _path_picker(self, parent: ctk.CTkFrame, label: str, variable: StringVar, row: int, command) -> None:
        ctk.CTkLabel(parent, text=label, text_color="#cbd5e1", anchor="w").grid(row=row, column=0, sticky="ew", padx=12, pady=(12 if row == 0 else 8, 4))
        line = ctk.CTkFrame(parent, fg_color="transparent")
        line.grid(row=row + 1, column=0, sticky="ew", padx=12)
        line.grid_columnconfigure(0, weight=1)
        ctk.CTkEntry(line, textvariable=variable, height=34, corner_radius=8).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ctk.CTkButton(line, text="选择", width=64, height=34, corner_radius=8, fg_color="#334155", hover_color="#475569", command=command).grid(row=0, column=1)

    def _render_nav(self) -> None:
        for child in self.nav_frame.winfo_children():
            child.destroy()
        for index, (view, label) in enumerate(VIEW_LABELS.items()):
            active = view == self.view
            button = ctk.CTkButton(
                self.nav_frame,
                text=label,
                height=36,
                corner_radius=8,
                anchor="w",
                fg_color="#263244" if active else "transparent",
                hover_color="#263244",
                text_color="#ffffff" if active else "#cbd5e1",
                command=lambda value=view: self.set_view(value),
            )
            button.grid(row=index, column=0, sticky="ew", pady=2)

    def pick_source(self) -> None:
        folder = filedialog.askdirectory(initialdir=self.source_var.get() or str(Path.home()), title="选择原图文件夹")
        if folder:
            self.source_var.set(folder)

    def pick_output(self) -> None:
        folder = filedialog.askdirectory(initialdir=self.output_var.get() or str(Path.home()), title="选择输出文件夹")
        if folder:
            self.output_var.set(folder)

    def set_status(self, text: str) -> None:
        message = text or "准备就绪"
        self.status_label.configure(text=message)
        self.side_status.configure(text=message)

    def scan_async(self) -> None:
        folder = self.source_var.get().strip()
        self.scan_button.configure(state="disabled", text="筛选中...")
        self.set_status("正在筛选图片，原图不会被删除或移动...")
        thread = threading.Thread(target=self._scan_worker, args=(folder, self.threshold_var.get(), self.recursive_var.get()), daemon=True)
        thread.start()

    def _scan_worker(self, folder: str, threshold: int, recursive: bool) -> None:
        try:
            summary = scan_folder(folder, similar_threshold=threshold, recursive=recursive)
            self.events.put(("scan_done", summary))
        except Exception as exc:  # noqa: BLE001
            self.events.put(("error", str(exc)))

    def _poll_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                self.scan_button.configure(state="normal", text="开始筛选")
                if kind == "scan_done":
                    self.checked_ids.clear()
                    self.view = "recommend"
                    self._render_nav()
                    summary = payload
                    self.load_stats()
                    self.load_content()
                    self.set_status(f"筛选完成：{summary.total} 张，重复 {summary.exact_groups} 组，相似 {summary.similar_groups} 组。")
                elif kind == "error":
                    messagebox.showerror("筛图失败", str(payload))
                    self.set_status(str(payload))
        except queue.Empty:
            pass
        self.after(150, self._poll_events)

    def load_stats(self) -> None:
        with connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM images").fetchone()[0]
            counts = {
                row["review_status"]: row["count"]
                for row in conn.execute("SELECT review_status, COUNT(*) count FROM images GROUP BY review_status")
            }
            duplicate_member_count = conn.execute(
                "SELECT COUNT(*) FROM images WHERE exact_group != '' OR name_group != '' OR similar_group != ''"
            ).fetchone()[0]
        duplicate_count = len(self.duplicate_keeper_rows()) if duplicate_member_count else 0
        values = {
            "all": total,
            "recommend": counts.get("selected", 0),
            "selected": counts.get("selected", 0),
            "weak": counts.get("weak", 0),
            "empty": counts.get("empty", 0),
            "waste": counts.get("waste", 0),
            "duplicate": duplicate_count,
        }
        for child in self.stats_frame.winfo_children():
            child.destroy()
        for column, (view, label) in enumerate(VIEW_LABELS.items()):
            active = view == self.view
            card = ctk.CTkButton(
                self.stats_frame,
                text=f"{label}\n{values.get(view, 0)}",
                height=66,
                corner_radius=10,
                fg_color="#dff5ed" if active else "#ffffff",
                hover_color="#dff5ed",
                text_color="#111827",
                border_width=1,
                border_color="#97dac3" if active else "#dbe3ec",
                font=("Microsoft YaHei UI", 13, "bold"),
                command=lambda value=view: self.set_view(value),
            )
            card.grid(row=0, column=column, sticky="ew", padx=(0, 8))
            self.stats_frame.grid_columnconfigure(column, weight=1)

    def set_view(self, view: str) -> None:
        self.view = view
        self._render_nav()
        self.load_stats()
        self.load_content()

    def load_content(self) -> None:
        self.rows = self.query_rows()
        self.title_label.configure(text=VIEW_LABELS.get(self.view, "筛选结果"))
        if self.view == "duplicate":
            self.set_status(f"{len(self.rows)} 张重复去重结果；每个重复/相似组只保留最佳。已勾选 {len(self.checked_ids)} 张。")
        else:
            self.set_status(f"{len(self.rows)} 张图片，已勾选 {len(self.checked_ids)} 张。")
        self.render_grid()

    def query_rows(self) -> list[dict[str, object]]:
        if self.view == "duplicate":
            rows = self.duplicate_keeper_rows()
            search = self.search_var.get().strip().lower()
            if search:
                rows = [row for row in rows if search in str(row["name"]).lower()]
            return rows

        clauses: list[str] = []
        params: list[object] = []
        if self.view in STATUS_LABELS:
            clauses.append("review_status = ?")
            params.append(self.view)
        elif self.view == "recommend":
            clauses.append("review_status = 'selected'")
        search = self.search_var.get().strip()
        if search:
            clauses.append("name LIKE ?")
            params.append(f"%{search}%")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM images
                {where}
                ORDER BY
                    CASE review_status
                        WHEN 'selected' THEN 0
                        WHEN 'weak' THEN 1
                        WHEN 'empty' THEN 2
                        WHEN 'waste' THEN 3
                        ELSE 4
                    END,
                    quality_score DESC,
                    name COLLATE NOCASE
                LIMIT 1000
                """,
                params,
            ).fetchall()
        return [row_to_dict(row) for row in rows]

    def render_grid(self) -> None:
        for child in self.grid_container.winfo_children():
            child.destroy()
        self.image_refs.clear()
        width = max(self.main.winfo_width(), 820)
        columns = max(2, min(5, (width - 80) // 228))
        for index, row in enumerate(self.rows):
            card = self._create_card(self.grid_container, row)
            card.grid(row=index // columns, column=index % columns, sticky="nwe", padx=7, pady=7)
            self.grid_container.grid_columnconfigure(index % columns, weight=1)

    def _create_card(self, parent: ctk.CTkFrame, row: dict[str, object]) -> ctk.CTkFrame:
        image_id = int(row["id"])
        status = str(row.get("review_status") or "selected")
        card = ctk.CTkFrame(parent, width=210, corner_radius=10, border_width=1, border_color="#dbe3ec", fg_color="#ffffff")
        card.grid_propagate(False)
        card.configure(height=310)

        header = ctk.CTkFrame(card, fg_color="transparent")
        header.pack(fill="x", padx=10, pady=(10, 4))
        variable = BooleanVar(value=image_id in self.checked_ids)
        self.check_vars[image_id] = variable
        ctk.CTkCheckBox(header, text="", width=24, variable=variable, command=lambda value=image_id: self.toggle_checked(value)).pack(side="left")
        ctk.CTkLabel(header, text=STATUS_LABELS.get(status, status), width=48, height=24, corner_radius=6, fg_color=STATUS_COLORS.get(status, "#64748b"), text_color="white", font=("Microsoft YaHei UI", 11, "bold")).pack(side="right")

        photo = self._load_thumb(image_id)
        image_label = ctk.CTkLabel(card, text="", image=photo, height=132)
        image_label.pack(fill="x", padx=10)
        image_label.bind("<Double-Button-1>", lambda _event, value=row: self.open_original(value))

        ctk.CTkLabel(card, text=str(row["name"]), text_color="#111827", anchor="w", justify="left", wraplength=184, font=("Microsoft YaHei UI", 12, "bold")).pack(fill="x", padx=10, pady=(8, 0))
        stars = "★" * int(row.get("star_rating") or 0)
        ctk.CTkLabel(card, text=f"{stars or '未评分'}  分数 {round(float(row.get('quality_score') or 0))}", text_color="#64748b", anchor="w", font=("Microsoft YaHei UI", 11)).pack(fill="x", padx=10, pady=(2, 0))
        tags = str(row.get("tags") or "无标签")
        ctk.CTkLabel(card, text=tags, text_color="#64748b", anchor="w", wraplength=184, font=("Microsoft YaHei UI", 11)).pack(fill="x", padx=10, pady=(0, 8))

        buttons = ctk.CTkFrame(card, fg_color="transparent")
        buttons.pack(fill="x", padx=8, pady=(0, 8))
        for column, (status_key, label) in enumerate(STATUS_LABELS.items()):
            button = ctk.CTkButton(buttons, text=label, width=44, height=28, corner_radius=7, fg_color="#eef2f7", hover_color="#dbe3ec", text_color="#111827", font=("Microsoft YaHei UI", 11), command=lambda image_id=image_id, status_key=status_key: self.update_status(image_id, status_key))
            button.grid(row=0, column=column, sticky="ew", padx=2)
            buttons.grid_columnconfigure(column, weight=1)
        return card

    def _load_thumb(self, image_id: int) -> ctk.CTkImage:
        path = THUMBS_DIR / f"{image_id}.jpg"
        if path.exists():
            image = Image.open(path).convert("RGB")
        else:
            image = Image.new("RGB", (184, 132), "#eef2f7")
        image.thumbnail((184, 132), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (184, 132), "#f8fafc")
        canvas.paste(image, ((184 - image.width) // 2, (132 - image.height) // 2))
        photo = ctk.CTkImage(light_image=canvas, dark_image=canvas, size=(184, 132))
        self.image_refs[image_id] = photo
        return photo

    def toggle_checked(self, image_id: int) -> None:
        variable = self.check_vars[image_id]
        if variable.get():
            self.checked_ids.add(image_id)
        else:
            self.checked_ids.discard(image_id)
        self.set_status(f"{len(self.rows)} 张图片，已勾选 {len(self.checked_ids)} 张。")

    def check_all_current(self) -> None:
        for row in self.rows:
            image_id = int(row["id"])
            self.checked_ids.add(image_id)
            if image_id in self.check_vars:
                self.check_vars[image_id].set(True)
        self.set_status(f"已勾选当前 {len(self.rows)} 张。")

    def check_deduped_result(self) -> None:
        rows = self.duplicate_keeper_rows() if self.view == "duplicate" else self.deduped_rows(include_unique=True)
        self.checked_ids = {int(row["id"]) for row in rows}
        for image_id, variable in self.check_vars.items():
            variable.set(image_id in self.checked_ids)
        self.set_status(f"已勾选去重结果 {len(self.checked_ids)} 张。")

    def clear_checked(self) -> None:
        self.checked_ids.clear()
        for variable in self.check_vars.values():
            variable.set(False)
        self.set_status("已清空勾选。")

    def update_status(self, image_id: int, status: str) -> None:
        with connect() as conn:
            conn.execute("UPDATE images SET review_status = ? WHERE id = ?", (status, image_id))
        self.load_stats()
        self.load_content()

    def export_checked(self) -> None:
        if not self.checked_ids:
            messagebox.showinfo("没有勾选", "先勾选要导出的图片。")
            return
        rows = self.rows_by_ids(self.checked_ids)
        copied = self.copy_rows(rows, self.output_root() / "手动勾选")
        self.set_status(f"已导出勾选 {copied} 张，原图未删除。")

    def export_current_view(self) -> None:
        if not self.rows:
            messagebox.showinfo("没有图片", "当前分类没有可导出的图片。")
            return
        label = "重复去重" if self.view == "duplicate" else VIEW_LABELS.get(self.view, "当前分类")
        copied = self.copy_rows(self.rows, self.output_root() / label)
        self.set_status(f"已导出 {label} {copied} 张，原图未删除。")

    def export_deduped_all(self) -> None:
        rows = self.deduped_rows(include_unique=True)
        if not rows:
            messagebox.showinfo("没有图片", "当前没有可导出的图片。")
            return
        copied = self.copy_rows(rows, self.output_root() / "去重后全部")
        self.set_status(f"已导出去重后全部 {copied} 张，原图未删除。")

    def export_all_categories(self) -> None:
        root = self.output_root() / "按分类整理"
        total = 0
        with connect() as conn:
            for status, label in STATUS_LABELS.items():
                rows = [row_to_dict(row) for row in conn.execute("SELECT * FROM images WHERE review_status = ? ORDER BY quality_score DESC", (status,))]
                total += self.copy_rows(rows, root / label)
        self.set_status(f"已按分类导出 {total} 张，原图未删除。")

    def rows_by_ids(self, image_ids: set[int]) -> list[dict[str, object]]:
        if not image_ids:
            return []
        placeholders = ",".join("?" for _ in image_ids)
        with connect() as conn:
            rows = conn.execute(f"SELECT * FROM images WHERE id IN ({placeholders}) ORDER BY quality_score DESC", tuple(image_ids)).fetchall()
        return [row_to_dict(row) for row in rows]

    def duplicate_keeper_rows(self) -> list[dict[str, object]]:
        return self.deduped_rows(include_unique=False)

    def deduped_rows(self, include_unique: bool) -> list[dict[str, object]]:
        rows = self.all_rows()
        if not rows:
            return []
        row_by_id = {int(row["id"]): row for row in rows}
        parent = {image_id: image_id for image_id in row_by_id}

        def find(value: int) -> int:
            while parent[value] != value:
                parent[value] = parent[parent[value]]
                value = parent[value]
            return value

        def union(left: int, right: int) -> None:
            root_left = find(left)
            root_right = find(right)
            if root_left != root_right:
                parent[root_right] = root_left

        for column in ("exact_group", "name_group", "similar_group"):
            groups: dict[str, list[int]] = defaultdict(list)
            for row in rows:
                group_id = str(row.get(column) or "")
                if group_id:
                    groups[group_id].append(int(row["id"]))
            for members in groups.values():
                first = members[0]
                for member in members[1:]:
                    union(first, member)

        components: dict[int, list[dict[str, object]]] = defaultdict(list)
        for image_id, row in row_by_id.items():
            components[find(image_id)].append(row)

        keepers: list[dict[str, object]] = []
        for members in components.values():
            if not include_unique and len(members) == 1:
                continue
            keepers.append(max(members, key=self.keeper_score))
        keepers.sort(key=self.keeper_score, reverse=True)
        return keepers

    def all_rows(self) -> list[dict[str, object]]:
        with connect() as conn:
            rows = conn.execute("SELECT * FROM images ORDER BY quality_score DESC, name COLLATE NOCASE").fetchall()
        return [row_to_dict(row) for row in rows]

    @staticmethod
    def keeper_score(row: dict[str, object]) -> tuple[float, int, int]:
        return (float(row.get("quality_score") or 0), int(row.get("star_rating") or 0), int(row.get("size_bytes") or 0))

    def output_root(self) -> Path:
        target = Path(self.output_var.get().strip() or DEFAULT_OUTPUT_FOLDER).expanduser().resolve()
        target.mkdir(parents=True, exist_ok=True)
        return target

    def copy_rows(self, rows: list[dict[str, object]], target: Path) -> int:
        target.mkdir(parents=True, exist_ok=True)
        copied = 0
        for row in rows:
            source = Path(str(row["path"]))
            if not source.exists():
                continue
            shutil.copy2(source, target / f"{int(row['id']):04d}_{source.name}")
            copied += 1
        return copied

    def open_output(self) -> None:
        os.startfile(str(self.output_root()))  # type: ignore[attr-defined]

    def open_original(self, row: dict[str, object]) -> None:
        path = Path(str(row["path"]))
        if path.exists():
            os.startfile(str(path))  # type: ignore[attr-defined]


def main() -> None:
    app = DesktopApp()
    app.mainloop()

