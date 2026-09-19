"""MyChar Sync — two-pane merge for players, NPCs and notes."""

from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable

from sync_core import (
    APP_VERSION,
    STATUS_LABEL,
    Category,
    DiffRow,
    Document,
    character_label,
    copy_characters,
    copy_items,
    diff_lists,
    get_character,
    get_items,
    item_id,
    item_name,
    load_document,
    reassign_character_id,
    save_document,
    set_items,
)

BG = "#121018"
BG2 = "#1c1824"
BG3 = "#2a2433"
FG = "#f3e6c8"
FG_DIM = "#b8a88a"
ACCENT = "#e08a3c"
ACCENT2 = "#c9a227"
OK = "#7cb87c"
DIFF = "#e0b85a"
ONLY_L = "#6aa7d4"
ONLY_R = "#c984d4"

TAB_DEFS: list[tuple[Category, str]] = [
    ("players", "Игроки"),
    ("allies", "НПС"),
    ("notes", "Заметки"),
    ("characters", "Персонажи"),
]


def start_dir() -> str:
    for path in (
        Path(r"F:\Documents\dnd"),
        Path.home() / "Documents" / "dnd",
        Path.home() / "Documents",
    ):
        if path.is_dir():
            return str(path)
    return str(Path.home())


class Pane(ttk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        heading: str,
        on_select: Callable[[DiffRow, str], None],
        on_toggle: Callable[[], None],
    ) -> None:
        super().__init__(master)
        self.on_select = on_select
        self.on_toggle = on_toggle
        self.rows: list[DiffRow] = []
        self.side = "left"
        self.checked: set[str] = set()

        head = ttk.Frame(self)
        head.pack(fill="x", pady=(0, 6))
        self.title_var = tk.StringVar(value=heading)
        ttk.Label(head, textvariable=self.title_var, style="H.TLabel").pack(side="left")
        self.count_var = tk.StringVar(value="")
        ttk.Label(head, textvariable=self.count_var, style="D.TLabel").pack(side="right")

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)

        columns = ("mark", "name", "extra", "status")
        self.tree = ttk.Treeview(body, columns=columns, show="headings", selectmode="browse")
        self.tree.heading("mark", text="")
        self.tree.heading("name", text="Имя")
        self.tree.heading("extra", text="Детали")
        self.tree.heading("status", text="Статус")
        self.tree.column("mark", width=36, minwidth=36, stretch=False, anchor="center")
        self.tree.column("name", width=180, stretch=True, anchor="w")
        self.tree.column("extra", width=180, stretch=True, anchor="w")
        self.tree.column("status", width=110, minwidth=90, stretch=False, anchor="w")
        scroll = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        self.tree.tag_configure("same", foreground=OK)
        self.tree.tag_configure("different", foreground=DIFF)
        self.tree.tag_configure("left_only", foreground=ONLY_L)
        self.tree.tag_configure("right_only", foreground=ONLY_R)

        self.tree.bind("<<TreeviewSelect>>", self._pick)
        self.tree.bind("<Button-1>", self._click)
        self.tree.bind("<space>", self._space)

        btns = ttk.Frame(self)
        btns.pack(fill="x", pady=(6, 0))
        ttk.Button(btns, text="Отметить нужные", command=self.check_needed).pack(side="left")
        ttk.Button(btns, text="Все", command=self.check_all).pack(side="left", padx=4)
        ttk.Button(btns, text="Снять", command=self.check_none).pack(side="left")

    def set_heading(self, text: str) -> None:
        self.title_var.set(text)

    def load(self, rows: list[DiffRow], side: str) -> None:
        self.rows = rows
        self.side = side
        self.checked = set()
        for row in rows:
            item = row.left if side == "left" else row.right
            if item is None:
                continue
            if side == "left" and row.status in {"different", "left_only"}:
                self.checked.add(row.key)
            if side == "right" and row.status in {"different", "right_only"}:
                self.checked.add(row.key)
        self._redraw()

    def visible_rows(self) -> list[DiffRow]:
        out: list[DiffRow] = []
        for row in self.rows:
            item = row.left if self.side == "left" else row.right
            if item is not None:
                out.append(row)
        return out

    def _redraw(self) -> None:
        selected = self.tree.selection()
        keep = selected[0] if selected else None
        self.tree.delete(*self.tree.get_children())
        visible = self.visible_rows()
        for row in visible:
            mark = "☑" if row.key in self.checked else "☐"
            self.tree.insert(
                "",
                "end",
                iid=row.key,
                values=(mark, row.label, row.extra, STATUS_LABEL[row.status]),
                tags=(row.status,),
            )
            if keep == row.key:
                self.tree.selection_set(row.key)
        self.count_var.set(f"{len(self.checked)} / {len(visible)}")

    def _row(self, iid: str) -> DiffRow | None:
        for row in self.rows:
            if row.key == iid:
                return row
        return None

    def _click(self, event: tk.Event) -> str | None:
        col = self.tree.identify_column(event.x)
        iid = self.tree.identify_row(event.y)
        if iid and col == "#1":
            self._toggle(iid)
            return "break"
        return None

    def _space(self, _event: tk.Event) -> str:
        selected = self.tree.selection()
        if selected:
            self._toggle(selected[0])
        return "break"

    def _toggle(self, iid: str) -> None:
        if iid in self.checked:
            self.checked.discard(iid)
        else:
            self.checked.add(iid)
        self._redraw()
        self.tree.selection_set(iid)
        self.on_toggle()

    def _pick(self, _event: tk.Event | None = None) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        row = self._row(selected[0])
        if row:
            self.on_select(row, self.side)

    def check_needed(self) -> None:
        self.checked = set()
        for row in self.visible_rows():
            if self.side == "left" and row.status in {"different", "left_only"}:
                self.checked.add(row.key)
            if self.side == "right" and row.status in {"different", "right_only"}:
                self.checked.add(row.key)
        self._redraw()
        self.on_toggle()

    def check_all(self) -> None:
        self.checked = {row.key for row in self.visible_rows()}
        self._redraw()
        self.on_toggle()

    def check_none(self) -> None:
        self.checked.clear()
        self._redraw()
        self.on_toggle()

    def selected_items(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for row in self.visible_rows():
            if row.key not in self.checked:
                continue
            item = row.left if self.side == "left" else row.right
            if item is not None:
                items.append(item)
        return items


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"MyChar Sync {APP_VERSION}")
        self.geometry("1240x780")
        self.minsize(960, 620)
        self.configure(bg=BG)

        self.left_doc: Document | None = None
        self.right_doc: Document | None = None
        self.left_char_choice = tk.StringVar()
        self.right_char_choice = tk.StringVar()
        self.status_text = tk.StringVar(
            value="Откройте два JSON — выгрузку героя или полную резервную копию."
        )
        self.left_map: dict[str, str] = {}
        self.right_map: dict[str, str] = {}
        self.panes: dict[Category, dict[str, Pane]] = {}
        self.left_new_id = tk.BooleanVar(value=True)
        self.right_new_id = tk.BooleanVar(value=True)

        self._setup_style()
        self._build()

    def _setup_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", background=BG, foreground=FG, fieldbackground=BG2, bordercolor=BG3)
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=BG2)
        style.configure("TLabel", background=BG, foreground=FG, font=("Segoe UI", 10))
        style.configure("H.TLabel", background=BG, foreground=ACCENT, font=("Segoe UI Semibold", 12))
        style.configure("D.TLabel", background=BG, foreground=FG_DIM, font=("Segoe UI", 9))
        style.configure("TButton", background=BG3, foreground=FG, font=("Segoe UI", 9), padding=6)
        style.map("TButton", background=[("active", "#3a3344")])
        style.configure("A.TButton", background=ACCENT, foreground="#1a1208", font=("Segoe UI Semibold", 10))
        style.map("A.TButton", background=[("active", "#f0a050")])
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure(
            "TNotebook.Tab",
            background=BG3,
            foreground=FG,
            padding=(16, 8),
            font=("Segoe UI Semibold", 10),
        )
        style.map("TNotebook.Tab", background=[("selected", ACCENT)], foreground=[("selected", "#1a1208")])
        style.configure(
            "Treeview",
            background=BG2,
            foreground=FG,
            fieldbackground=BG2,
            rowheight=28,
            font=("Segoe UI", 10),
            bordercolor=BG3,
        )
        style.configure("Treeview.Heading", background=BG3, foreground=ACCENT2, font=("Segoe UI Semibold", 9))
        style.map("Treeview", background=[("selected", "#3d3348")], foreground=[("selected", FG)])
        style.configure("TCombobox", fieldbackground=BG2, background=BG3, foreground=FG)
        style.configure("TCheckbutton", background=BG, foreground=FG, font=("Segoe UI", 9))
        style.map("TCheckbutton", background=[("active", BG)], foreground=[("active", FG)])
        style.configure("S.TLabel", background=BG3, foreground=FG_DIM, font=("Segoe UI", 9), padding=6)

    def _build(self) -> None:
        top = ttk.Frame(self, style="Card.TFrame")
        top.pack(fill="x", padx=12, pady=(12, 8))

        left_box = ttk.Frame(top)
        left_box.pack(side="left", fill="x", expand=True, padx=10, pady=10)
        ttk.Label(left_box, text="Слева", style="H.TLabel").pack(anchor="w")
        self.left_path_var = tk.StringVar(value="файл не выбран")
        ttk.Label(left_box, textvariable=self.left_path_var, style="D.TLabel").pack(anchor="w")
        row = ttk.Frame(left_box)
        row.pack(fill="x", pady=(6, 0))
        ttk.Button(row, text="Открыть…", command=lambda: self.open_file("left")).pack(side="left")
        ttk.Button(row, text="Сохранить", command=lambda: self.save_side("left")).pack(side="left", padx=4)
        ttk.Button(row, text="Сохранить как…", command=lambda: self.save_side("left", save_as=True)).pack(side="left")
        self.left_combo = ttk.Combobox(left_box, textvariable=self.left_char_choice, state="readonly")
        self.left_combo.pack(fill="x", pady=(8, 0))
        self.left_combo.bind("<<ComboboxSelected>>", lambda _e: self.refresh_tabs())
        ttk.Checkbutton(
            left_box,
            text="Новый id при сохранении (чтобы импорт не попал в старого героя)",
            variable=self.left_new_id,
        ).pack(anchor="w", pady=(6, 0))

        right_box = ttk.Frame(top)
        right_box.pack(side="right", fill="x", expand=True, padx=10, pady=10)
        ttk.Label(right_box, text="Справа", style="H.TLabel").pack(anchor="w")
        self.right_path_var = tk.StringVar(value="файл не выбран")
        ttk.Label(right_box, textvariable=self.right_path_var, style="D.TLabel").pack(anchor="w")
        row = ttk.Frame(right_box)
        row.pack(fill="x", pady=(6, 0))
        ttk.Button(row, text="Открыть…", command=lambda: self.open_file("right")).pack(side="left")
        ttk.Button(row, text="Сохранить", command=lambda: self.save_side("right")).pack(side="left", padx=4)
        ttk.Button(row, text="Сохранить как…", command=lambda: self.save_side("right", save_as=True)).pack(side="left")
        self.right_combo = ttk.Combobox(right_box, textvariable=self.right_char_choice, state="readonly")
        self.right_combo.pack(fill="x", pady=(8, 0))
        self.right_combo.bind("<<ComboboxSelected>>", lambda _e: self.refresh_tabs())
        ttk.Checkbutton(
            right_box,
            text="Новый id при сохранении (чтобы импорт не попал в старого героя)",
            variable=self.right_new_id,
        ).pack(anchor="w", pady=(6, 0))

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        self.nb.bind("<<NotebookTabChanged>>", lambda _e: self.on_tab_change())

        for cat, title in TAB_DEFS:
            page = ttk.Frame(self.nb)
            self.nb.add(page, text=title)
            lists = ttk.Frame(page)
            lists.pack(fill="both", expand=True, padx=8, pady=8)

            left_pane = Pane(lists, "Слева", self.on_row_select, self.update_status)
            mid = ttk.Frame(lists)
            right_pane = Pane(lists, "Справа", self.on_row_select, self.update_status)

            left_pane.pack(side="left", fill="both", expand=True)
            mid.pack(side="left", fill="y", padx=10)
            right_pane.pack(side="left", fill="both", expand=True)

            ttk.Label(mid, text="Перенос", style="D.TLabel").pack(pady=(40, 8))
            ttk.Button(
                mid,
                text="→  вправо",
                style="A.TButton",
                command=lambda c=cat: self.transfer("left", c),
            ).pack(fill="x", pady=4)
            ttk.Button(
                mid,
                text="←  влево",
                style="A.TButton",
                command=lambda c=cat: self.transfer("right", c),
            ).pack(fill="x", pady=4)
            ttk.Label(mid, text="Отметьте,\nчто копировать", style="D.TLabel", justify="center").pack(
                pady=(16, 0)
            )
            self.panes[cat] = {"left": left_pane, "right": right_pane}

        preview_wrap = ttk.Frame(self)
        preview_wrap.pack(fill="x", padx=12, pady=(0, 8))
        ttk.Label(preview_wrap, text="Сравнение выбранной записи", style="H.TLabel").pack(anchor="w")
        panes = ttk.Frame(preview_wrap)
        panes.pack(fill="x", pady=(4, 0))
        self.preview_left = tk.Text(
            panes, height=8, wrap="word", bg=BG2, fg=FG, insertbackground=FG, relief="flat", font=("Consolas", 9)
        )
        self.preview_right = tk.Text(
            panes, height=8, wrap="word", bg=BG2, fg=FG, insertbackground=FG, relief="flat", font=("Consolas", 9)
        )
        self.preview_left.pack(side="left", fill="both", expand=True, padx=(0, 4))
        self.preview_right.pack(side="left", fill="both", expand=True, padx=(4, 0))
        self.preview_left.configure(state="disabled")
        self.preview_right.configure(state="disabled")

        ttk.Label(self, textvariable=self.status_text, style="S.TLabel", anchor="w").pack(
            fill="x", side="bottom"
        )

        menubar = tk.Menu(self, tearoff=0, bg=BG2, fg=FG)
        file_menu = tk.Menu(menubar, tearoff=0, bg=BG2, fg=FG)
        file_menu.add_command(label="Открыть слева…", command=lambda: self.open_file("left"))
        file_menu.add_command(label="Открыть справа…", command=lambda: self.open_file("right"))
        file_menu.add_separator()
        file_menu.add_command(label="Сохранить слева", command=lambda: self.save_side("left"))
        file_menu.add_command(label="Сохранить справа", command=lambda: self.save_side("right"))
        file_menu.add_command(label="Сохранить оба", command=self.save_both)
        file_menu.add_separator()
        file_menu.add_command(label="Выход", command=self.destroy)
        menubar.add_cascade(label="Файл", menu=file_menu)
        self.config(menu=menubar)
        self.bind("<Control-s>", lambda _e: self.save_both())

    def current_category(self) -> Category:
        return TAB_DEFS[self.nb.index("current")][0]

    def on_tab_change(self) -> None:
        self.fill_tab(self.current_category())
        self.set_preview(None)
        self.update_status()

    def open_file(self, side: str) -> None:
        path = filedialog.askopenfilename(
            title="Открыть JSON MyChar",
            filetypes=[("JSON", "*.json"), ("Все файлы", "*.*")],
            initialdir=start_dir(),
        )
        if not path:
            return
        try:
            doc = load_document(path)
        except Exception as exc:
            messagebox.showerror("Не удалось открыть", str(exc))
            return
        if side == "left":
            self.left_doc = doc
            self.left_path_var.set(path)
        else:
            self.right_doc = doc
            self.right_path_var.set(path)
        self.reload_combo(side)
        self.refresh_tabs()
        self.status_text.set(f"Открыт {doc.title}: {len(doc.characters)} персонаж(ей).")

    def reload_combo(self, side: str, keep_id: str | None = None) -> None:
        doc = self.left_doc if side == "left" else self.right_doc
        combo = self.left_combo if side == "left" else self.right_combo
        choice = self.left_char_choice if side == "left" else self.right_char_choice
        mapping: dict[str, str] = {}
        labels: list[str] = []
        if doc:
            for char in doc.characters:
                cid = item_id(char) or item_name(char)
                text = character_label(char)
                mapping[text] = cid
                labels.append(text)
        combo["values"] = labels
        selected = labels[0] if labels else ""
        if keep_id:
            for text, cid in mapping.items():
                if cid == keep_id:
                    selected = text
                    break
        choice.set(selected)
        if side == "left":
            self.left_map = mapping
        else:
            self.right_map = mapping

    def selected_char(self, side: str) -> dict[str, Any] | None:
        doc = self.left_doc if side == "left" else self.right_doc
        if not doc:
            return None
        mapping = self.left_map if side == "left" else self.right_map
        choice = self.left_char_choice if side == "left" else self.right_char_choice
        return get_character(doc, mapping.get(choice.get()))

    def refresh_tabs(self) -> None:
        for cat, _title in TAB_DEFS:
            self.fill_tab(cat)
        self.update_status()

    def fill_tab(self, category: Category) -> None:
        ui = self.panes[category]
        if category == "characters":
            left_items = list(self.left_doc.characters) if self.left_doc else []
            right_items = list(self.right_doc.characters) if self.right_doc else []
        else:
            left_items = get_items(self.selected_char("left"), category)
            right_items = get_items(self.selected_char("right"), category)
        rows = diff_lists(left_items, right_items, category)
        left_name = "Слева"
        right_name = "Справа"
        if category != "characters":
            left_char = self.selected_char("left")
            right_char = self.selected_char("right")
            if left_char:
                left_name = item_name(left_char) or left_name
            if right_char:
                right_name = item_name(right_char) or right_name
        ui["left"].set_heading(left_name)
        ui["right"].set_heading(right_name)
        ui["left"].load(rows, "left")
        ui["right"].load(rows, "right")

    def on_row_select(self, row: DiffRow, side: str) -> None:
        self.set_preview(row)
        other = self.panes[self.current_category()]["right" if side == "left" else "left"]
        try:
            other.tree.selection_set(row.key)
            other.tree.see(row.key)
        except tk.TclError:
            pass

    def set_preview(self, row: DiffRow | None) -> None:
        def show(widget: tk.Text, item: dict[str, Any] | None, empty: str) -> None:
            widget.configure(state="normal")
            widget.delete("1.0", "end")
            if item is None:
                widget.insert("1.0", empty)
            else:
                text = json.dumps(item, ensure_ascii=False, indent=2)
                if len(text) > 4000:
                    text = text[:4000] + "\n…"
                widget.insert("1.0", text)
            widget.configure(state="disabled")

        if row is None:
            show(self.preview_left, None, "")
            show(self.preview_right, None, "")
            return
        show(self.preview_left, row.left, "нет записи")
        show(self.preview_right, row.right, "нет записи")

    def transfer(self, source_side: str, category: Category) -> None:
        src_doc = self.left_doc if source_side == "left" else self.right_doc
        dst_doc = self.right_doc if source_side == "left" else self.left_doc
        if not src_doc or not dst_doc:
            messagebox.showinfo("Нет файлов", "Сначала откройте JSON слева и справа.")
            return
        selected = self.panes[category][source_side].selected_items()
        if not selected:
            messagebox.showinfo("Ничего не отмечено", "Отметьте записи в списке, откуда копируете.")
            return
        dest_side = "right" if source_side == "left" else "left"
        if category == "characters":
            dst_doc.characters = copy_characters(selected, dst_doc.characters)
            if dst_doc.kind == "character" and len(dst_doc.characters) != 1:
                dst_doc.kind = "backup"
            dst_doc.dirty = True
            self.reload_combo(dest_side)
        else:
            dest_char = self.selected_char(dest_side)
            if dest_char is None:
                messagebox.showinfo("Нет персонажа", "На стороне назначения нет выбранного героя.")
                return
            updated = copy_items(
                selected,
                get_items(dest_char, category),
                name_key="title" if category == "notes" else "name",
                prefer_name=(category == "notes"),
            )
            set_items(dest_char, category, updated)
            dst_doc.dirty = True
        self.fill_tab(category)
        self.update_status()
        arrow = "→" if source_side == "left" else "←"
        self.status_text.set(f"Перенесено {len(selected)} записей {arrow}. Не забудьте сохранить файл.")

    def save_side(self, side: str, save_as: bool = False) -> None:
        doc = self.left_doc if side == "left" else self.right_doc
        if not doc:
            messagebox.showinfo("Нет файла", "Сначала откройте JSON.")
            return
        path: str | None = None
        if save_as or not doc.path:
            chosen = filedialog.asksaveasfilename(
                title="Сохранить JSON",
                defaultextension=".json",
                filetypes=[("JSON", "*.json")],
                initialfile=doc.path.name if doc.path else "mychar.json",
                initialdir=str(doc.path.parent) if doc.path else start_dir(),
            )
            if not chosen:
                return
            path = chosen
        want_new_id = (self.left_new_id if side == "left" else self.right_new_id).get()
        new_id: str | None = None
        if want_new_id:
            char = self.selected_char(side)
            if char is not None:
                new_id = reassign_character_id(char)
                doc.dirty = True
                self.reload_combo(side, keep_id=new_id)
        try:
            saved = save_document(doc, path)
        except Exception as exc:
            messagebox.showerror("Ошибка сохранения", str(exc))
            return
        if side == "left":
            self.left_path_var.set(str(saved))
        else:
            self.right_path_var.set(str(saved))
        if new_id:
            self.status_text.set(f"Сохранено: {saved}  •  новый id {new_id}")
        else:
            self.status_text.set(f"Сохранено: {saved}")

    def save_both(self) -> None:
        if self.left_doc:
            self.save_side("left")
        if self.right_doc:
            self.save_side("right")

    def update_status(self) -> None:
        cat = self.current_category()
        ui = self.panes[cat]
        left_n = len(ui["left"].checked)
        right_n = len(ui["right"].checked)
        left_dirty = " • не сохранено" if self.left_doc and self.left_doc.dirty else ""
        right_dirty = " • не сохранено" if self.right_doc and self.right_doc.dirty else ""
        self.status_text.set(
            f"Отмечено слева: {left_n}{left_dirty}   |   отмечено справа: {right_n}{right_dirty}   |   "
            "стрелка копирует отмеченное на другую сторону"
        )


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
