from __future__ import annotations

import os
import queue
import shutil
import threading
from pathlib import Path
from tkinter import BooleanVar, IntVar, StringVar, filedialog, messagebox, ttk
import tkinter as tk

from PIL import Image, ImageTk

from .db import THUMBS_DIR, connect, init_db, row_to_dict
from .scanner import scan_folder


DEFAULT_FOLDER = r"C:\Users\云电脑\Desktop\白底图\外贸绞肉机图"
DEFAULT_OUTPUT_FOLDER = r"C:\Users\云电脑\Desktop\晒图魔方输出"

REVIEW_LABELS = {
    "all": "全部",
    "recommend": "推荐",
    "selected": "精选",
    "weak": "较差",
    "empty": "空镜",
    "waste": "废片",
    "duplicate": "重复/相似",
}
STATUS_LABELS = {
    "selected": "精选",
    "weak": "较差",
    "empty": "空镜",
    "waste": "废片",
}
STATUS_COLORS = {
    "selected": "#0b8f67",
    "weak": "#c77718",
    "empty": "#6953c9",
    "waste": "#c83535",
}


class DesktopApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        init_db()
        self.title("筛图魔方")
        self.geometry("1280x820")
        self.minsize(1020, 680)
        self.configure(bg="#eef1f4")

        self.source_var = StringVar(value=DEFAULT_FOLDER)
        self.output_var = StringVar(value=DEFAULT_OUTPUT_FOLDER)
        self.threshold_var = IntVar(value=5)
        self.recursive_var = BooleanVar(value=False)
        self.search_var = StringVar(value="")
        self.view = "all"
        self.rows: list[dict[str, object]] = []
        self.checked_ids: set[int] = set()
        self.check_vars: dict[int, BooleanVar] = {}
        self.image_refs: dict[int, ImageTk.PhotoImage] = {}
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()

        self._build_style()
        self._build_layout()
        self.load_stats()
        self.load_content()
        self.after(150, self._poll_events)

    def _build_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background="#eef1f4")
        style.configure("Sidebar.TFrame", background="#151d2a")
        style.configure("Panel.TFrame", background="#101722", borderwidth=1, relief="solid")
        style.configure("Card.TFrame", background="#ffffff", borderwidth=1, relief="solid")
        style.configure("TLabel", background="#eef1f4", foreground="#1f252d")
        style.configure("Sidebar.TLabel", background="#151d2a", foreground="#dbe4ee")
        style.configure("Muted.TLabel", foreground="#687381")
        style.configure("Card.TLabel", background="#ffffff")
        style.configure("Primary.TButton", background="#13a579", foreground="#ffffff", borderwidth=0)
        style.map("Primary.TButton", background=[("active", "#0d745c"), ("disabled", "#9bbfb4")])
        style.configure("Nav.TButton", background="#151d2a", foreground="#c5cfdc", borderwidth=0, anchor="w")
        style.map("Nav.TButton", background=[("active", "#202b3d")])
        style.configure("ActiveNav.TButton", background="#202b3d", foreground="#ffffff", borderwidth=1, anchor="w")

    def _build_layout(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        sidebar = ttk.Frame(self, style="Sidebar.TFrame", padding=16)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_columnconfigure(0, weight=1)

        brand = ttk.Frame(sidebar, style="Sidebar.TFrame")
        brand.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        mark = tk.Label(brand, text="筛", width=3, height=2, bg="#13a579", fg="white", font=("Microsoft YaHei UI", 12, "bold"))
        mark.pack(side="left", padx=(0, 10))
        title_box = ttk.Frame(brand, style="Sidebar.TFrame")
        title_box.pack(side="left", fill="x", expand=True)
        ttk.Label(title_box, text="筛图魔方", style="Sidebar.TLabel", font=("Microsoft YaHei UI", 15, "bold")).pack(anchor="w")
        ttk.Label(title_box, text="Windows 原生筛图软件", style="Sidebar.TLabel", foreground="#95a3b5").pack(anchor="w")

        self.nav_frame = ttk.Frame(sidebar, style="Sidebar.TFrame")
        self.nav_frame.grid(row=1, column=0, sticky="ew", pady=(0, 14))
        self._render_nav()

        form = ttk.Frame(sidebar, style="Panel.TFrame", padding=12)
        form.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        form.grid_columnconfigure(0, weight=1)
        self._sidebar_entry(form, "原图文件夹", self.source_var, 0, self.pick_source)
        self._sidebar_entry(form, "输出文件夹", self.output_var, 2, self.pick_output)
        ttk.Label(form, text="相似严格度", style="Sidebar.TLabel").grid(row=4, column=0, sticky="w", pady=(8, 2))
        ttk.Scale(form, from_=0, to=16, variable=self.threshold_var, orient="horizontal").grid(row=5, column=0, sticky="ew")
        ttk.Checkbutton(form, text="包含子文件夹", variable=self.recursive_var).grid(row=6, column=0, sticky="w", pady=(8, 8))
        self.scan_button = ttk.Button(form, text="开始筛选", style="Primary.TButton", command=self.scan_async)
        self.scan_button.grid(row=7, column=0, sticky="ew")

        actions = ttk.Frame(sidebar, style="Panel.TFrame", padding=12)
        actions.grid(row=3, column=0, sticky="ew")
        actions.grid_columnconfigure(0, weight=1)
        action_buttons = [
            ("全选当前", self.check_all_current),
            ("清空勾选", self.clear_checked),
            ("导出勾选", self.export_checked),
            ("导出当前分类", self.export_current_view),
            ("按分类导出全部", self.export_all_categories),
            ("打开输出文件夹", self.open_output),
        ]
        for index, (text, command) in enumerate(action_buttons):
            row = index // 2
            column = index % 2
            ttk.Button(actions, text=text, command=command).grid(row=row, column=column, sticky="ew", padx=(0 if column == 0 else 6, 0), pady=(0, 7))
            actions.grid_columnconfigure(column, weight=1)

        self.side_status = tk.Label(sidebar, text="准备就绪", bg="#1a2434", fg="#c5cfdc", anchor="w", justify="left", padx=10, pady=9, wraplength=236)
        self.side_status.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        sidebar.grid_rowconfigure(5, weight=1)

        main = ttk.Frame(self, padding=18)
        main.grid(row=0, column=1, sticky="nsew")
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(3, weight=1)

        top = ttk.Frame(main)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        top.grid_columnconfigure(0, weight=1)
        self.title_label = ttk.Label(top, text="全部", font=("Microsoft YaHei UI", 20, "bold"))
        self.title_label.grid(row=0, column=0, sticky="w")
        search = ttk.Entry(top, textvariable=self.search_var)
        search.grid(row=0, column=1, sticky="e", ipadx=90)
        search.bind("<KeyRelease>", lambda _event: self.load_content())

        self.stats_frame = ttk.Frame(main)
        self.stats_frame.grid(row=1, column=0, sticky="ew", pady=(0, 10))

        self.status_label = ttk.Label(main, text="", style="Muted.TLabel")
        self.status_label.grid(row=2, column=0, sticky="ew", pady=(0, 8))

        holder = ttk.Frame(main)
        holder.grid(row=3, column=0, sticky="nsew")
        holder.grid_columnconfigure(0, weight=1)
        holder.grid_rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(holder, bg="#eef1f4", highlightthickness=0)
        scrollbar = ttk.Scrollbar(holder, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.grid_frame = ttk.Frame(self.canvas)
        self.canvas_window = self.canvas.create_window((0, 0), window=self.grid_frame, anchor="nw")
        self.grid_frame.bind("<Configure>", lambda _event: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self._resize_canvas_window)
        self.canvas.bind_all("<MouseWheel>", self._on_mouse_wheel)

    def _sidebar_entry(self, parent: ttk.Frame, label: str, variable: StringVar, row: int, command) -> None:
        ttk.Label(parent, text=label, style="Sidebar.TLabel").grid(row=row, column=0, sticky="w", pady=(0, 3))
        entry = ttk.Entry(parent, textvariable=variable)
        entry.grid(row=row + 1, column=0, sticky="ew")
        ttk.Button(parent, text="选择", command=command).grid(row=row + 1, column=1, padx=(8, 0))

    def _render_nav(self) -> None:
        for child in self.nav_frame.winfo_children():
            child.destroy()
        for index, (view, label) in enumerate(REVIEW_LABELS.items()):
            style = "ActiveNav.TButton" if view == self.view else "Nav.TButton"
            button = ttk.Button(self.nav_frame, text=label, style=style, command=lambda value=view: self.set_view(value))
            button.grid(row=index, column=0, sticky="ew", pady=2)

    def _resize_canvas_window(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self.canvas_window, width=event.width)

    def _on_mouse_wheel(self, event: tk.Event) -> None:
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def pick_source(self) -> None:
        folder = filedialog.askdirectory(initialdir=self.source_var.get() or str(Path.home()), title="选择原图文件夹")
        if folder:
            self.source_var.set(folder)

    def pick_output(self) -> None:
        folder = filedialog.askdirectory(initialdir=self.output_var.get() or str(Path.home()), title="选择输出文件夹")
        if folder:
            self.output_var.set(folder)

    def set_status(self, text: str) -> None:
        self.status_label.configure(text=text)
        self.side_status.configure(text=text or "准备就绪")

    def scan_async(self) -> None:
        folder = self.source_var.get().strip()
        self.scan_button.configure(state="disabled")
        self.set_status("正在筛选图片，原图不会被删除或移动...")
        thread = threading.Thread(target=self._scan_worker, args=(folder, self.threshold_var.get(), self.recursive_var.get()), daemon=True)
        thread.start()

    def _scan_worker(self, folder: str, threshold: int, recursive: bool) -> None:
        try:
            summary = scan_folder(folder, similar_threshold=threshold, recursive=recursive)
            self.events.put(("scan_done", summary))
        except Exception as exc:  # noqa: BLE001 - UI should surface the exact failure.
            self.events.put(("error", str(exc)))

    def _poll_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "scan_done":
                    self.scan_button.configure(state="normal")
                    self.checked_ids.clear()
                    self.view = "recommend"
                    self._render_nav()
                    summary = payload
                    self.load_stats()
                    self.load_content()
                    self.set_status(f"筛选完成：{summary.total} 张，重复 {summary.exact_groups} 组，相似 {summary.similar_groups} 组。")
                elif kind == "error":
                    self.scan_button.configure(state="normal")
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
            duplicate_count = conn.execute(
                "SELECT COUNT(*) FROM images WHERE exact_group != '' OR name_group != '' OR similar_group != ''"
            ).fetchone()[0]
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
        for column, (view, label) in enumerate(REVIEW_LABELS.items()):
            button = tk.Button(
                self.stats_frame,
                text=f"{label}\n{values.get(view, 0)}",
                bg="#ffffff" if view != self.view else "#e7f6f1",
                fg="#1f252d",
                relief="solid",
                bd=1,
                padx=14,
                pady=8,
                command=lambda value=view: self.set_view(value),
            )
            button.grid(row=0, column=column, sticky="ew", padx=(0, 8))
            self.stats_frame.grid_columnconfigure(column, weight=1)

    def set_view(self, view: str) -> None:
        self.view = view
        self._render_nav()
        self.load_stats()
        self.load_content()

    def load_content(self) -> None:
        self.rows = self.query_rows()
        self.title_label.configure(text=REVIEW_LABELS.get(self.view, "筛选结果"))
        self.set_status(f"{len(self.rows)} 张图片，已勾选 {len(self.checked_ids)} 张。")
        self.render_grid()

    def query_rows(self) -> list[dict[str, object]]:
        clauses: list[str] = []
        params: list[object] = []
        if self.view in STATUS_LABELS:
            clauses.append("review_status = ?")
            params.append(self.view)
        elif self.view == "recommend":
            clauses.append("review_status = 'selected'")
        elif self.view == "duplicate":
            clauses.append("(exact_group != '' OR name_group != '' OR similar_group != '')")
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
        for child in self.grid_frame.winfo_children():
            child.destroy()
        self.image_refs.clear()
        width = max(self.canvas.winfo_width(), 760)
        columns = max(2, min(6, width // 210))
        for index, row in enumerate(self.rows):
            card = self._create_card(self.grid_frame, row)
            card.grid(row=index // columns, column=index % columns, sticky="nwe", padx=6, pady=6)
            self.grid_frame.grid_columnconfigure(index % columns, weight=1)
        self.canvas.yview_moveto(0)

    def _create_card(self, parent: ttk.Frame, row: dict[str, object]) -> ttk.Frame:
        image_id = int(row["id"])
        card = ttk.Frame(parent, style="Card.TFrame", padding=8)
        top = ttk.Frame(card, style="Card.TFrame")
        top.pack(fill="x")
        variable = BooleanVar(value=image_id in self.checked_ids)
        self.check_vars[image_id] = variable
        ttk.Checkbutton(top, variable=variable, command=lambda value=image_id: self.toggle_checked(value)).pack(side="left")
        status = str(row.get("review_status") or "selected")
        tk.Label(top, text=STATUS_LABELS.get(status, status), bg=STATUS_COLORS.get(status, "#5c6674"), fg="white", padx=6, pady=2).pack(side="right")

        photo = self._load_thumb(image_id)
        image_label = ttk.Label(card, image=photo, style="Card.TLabel")
        image_label.pack(fill="x", pady=(7, 6))
        image_label.bind("<Double-Button-1>", lambda _event, value=row: self.open_original(value))

        name = ttk.Label(card, text=str(row["name"]), style="Card.TLabel", wraplength=172)
        name.pack(fill="x")
        stars = "★" * int(row.get("star_rating") or 0)
        ttk.Label(card, text=f"{stars or '未评分'}  分数 {round(float(row.get('quality_score') or 0))}", style="Card.TLabel", foreground="#687381").pack(fill="x", pady=(3, 0))
        tags = str(row.get("tags") or "")
        ttk.Label(card, text=tags or "无标签", style="Card.TLabel", foreground="#687381", wraplength=172).pack(fill="x", pady=(2, 6))

        buttons = ttk.Frame(card, style="Card.TFrame")
        buttons.pack(fill="x")
        for column, (status_key, label) in enumerate(STATUS_LABELS.items()):
            button = ttk.Button(buttons, text=label, command=lambda image_id=image_id, status_key=status_key: self.update_status(image_id, status_key))
            button.grid(row=0, column=column, sticky="ew", padx=1)
            buttons.grid_columnconfigure(column, weight=1)
        return card

    def _load_thumb(self, image_id: int) -> ImageTk.PhotoImage:
        path = THUMBS_DIR / f"{image_id}.jpg"
        if path.exists():
            image = Image.open(path).convert("RGB")
        else:
            image = Image.new("RGB", (180, 130), "#eef1f4")
        image.thumbnail((178, 130), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (178, 130), "#f4f6f8")
        canvas.paste(image, ((178 - image.width) // 2, (130 - image.height) // 2))
        photo = ImageTk.PhotoImage(canvas)
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
        label = REVIEW_LABELS.get(self.view, "当前分类")
        copied = self.copy_rows(self.rows, self.output_root() / label)
        self.set_status(f"已导出 {label} {copied} 张，原图未删除。")

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
