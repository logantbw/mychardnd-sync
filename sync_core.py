"""Load, compare and merge MyChar DnD JSON (character export or full backup)."""

from __future__ import annotations

import copy
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

APP_VERSION = "1.1"

BACKUP_FORMAT = "grimoire_backup_v1"
BACKUP_HINT = (
    "MyChar.DnD — полная резервная копия. Импорт: Герои → Импорт → выберите этот файл."
)

Kind = Literal["character", "backup"]
Status = Literal["same", "different", "left_only", "right_only"]
Category = Literal["players", "allies", "notes", "characters"]

CATEGORY_FIELD = {
    "players": "players",
    "allies": "allies",
    "notes": "customNotes",
}

STATUS_LABEL = {
    "same": "одинаковые",
    "different": "отличаются",
    "left_only": "нет справа",
    "right_only": "нет слева",
}


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def norm_text(value: Any) -> str:
    return " ".join(str(value or "").replace("ё", "е").replace("Ё", "Е").split()).casefold()


def item_id(item: dict[str, Any]) -> str:
    return str(item.get("id") or "").strip()


def item_name(item: dict[str, Any], name_key: str = "name") -> str:
    return str(item.get(name_key) or "").strip()


def character_label(char: dict[str, Any]) -> str:
    name = item_name(char) or "Без имени"
    class_name = str(char.get("class") or "")
    if isinstance(char.get("classes"), list) and char["classes"]:
        first = char["classes"][0] if isinstance(char["classes"][0], dict) else {}
        class_name = str(first.get("type") or class_name)
        level = first.get("level", char.get("level"))
    else:
        level = char.get("level")
    extra = " ".join(p for p in (class_name, str(level) if level not in (None, "") else "") if p)
    return f"{name} · {extra}" if extra else name


def player_extra(item: dict[str, Any]) -> str:
    bits = [item.get("race"), item.get("className"), item.get("relation")]
    return " · ".join(str(b) for b in bits if b)


def ally_extra(item: dict[str, Any]) -> str:
    relation = item.get("relationCustom") or item.get("relation")
    bits = [relation, item.get("location")]
    return " · ".join(str(b).strip() for b in bits if b)


def note_extra(item: dict[str, Any]) -> str:
    content = " ".join(str(item.get("content") or "").split())
    return content[:80] + ("…" if len(content) > 80 else "")


def comparable(item: dict[str, Any]) -> str:
    """Equality without id / collapsed — same person with different ids counts as same."""
    data = copy.deepcopy(item)
    data.pop("id", None)
    data.pop("collapsed", None)
    return json.dumps(data, ensure_ascii=False, sort_keys=True, default=str)


@dataclass
class Document:
    path: Path
    kind: Kind
    characters: list[dict[str, Any]]
    raw: dict[str, Any] | list[Any] | None = None
    theme: Any = None
    custom_spells: list[Any] = field(default_factory=list)
    dirty: bool = False

    @property
    def title(self) -> str:
        if self.kind == "character" and self.characters:
            return item_name(self.characters[0]) or self.path.name
        return self.path.name


@dataclass
class DiffRow:
    key: str
    status: Status
    label: str
    extra: str
    left: dict[str, Any] | None
    right: dict[str, Any] | None


def parse_document(data: Any, path: str | Path) -> Document:
    path = Path(path)
    if isinstance(data, list):
        return Document(path=path, kind="backup", characters=[_as_dict(x) for x in data], raw=data)

    if not isinstance(data, dict):
        raise ValueError("Ожидался JSON-объект персонажа или резервная копия.")

    fmt = str(data.get("format") or "")
    looks_backup = fmt == BACKUP_FORMAT or (
        "characters" in data and "name" not in data and isinstance(data.get("characters"), list)
    )
    if looks_backup:
        return Document(
            path=path,
            kind="backup",
            characters=[_as_dict(x) for x in _as_list(data.get("characters"))],
            raw=data,
            theme=data.get("theme"),
            custom_spells=_as_list(data.get("customSpells")),
        )

    if data.get("name") is not None or data.get("id") is not None:
        return Document(path=path, kind="character", characters=[dict(data)], raw=data)

    raise ValueError("Не похоже на выгрузку MyChar DnD.")


def load_document(path: str | Path) -> Document:
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    return parse_document(data, path)


def dumps_document(doc: Document) -> str:
    if doc.kind == "character" and len(doc.characters) == 1:
        payload: Any = doc.characters[0]
    else:
        base = dict(doc.raw) if isinstance(doc.raw, dict) else {}
        payload = {
            **base,
            "format": BACKUP_FORMAT,
            "exportedAt": datetime.now(timezone.utc).isoformat(),
            "appHint": base.get("appHint") or BACKUP_HINT,
            "theme": doc.theme if doc.theme is not None else base.get("theme"),
            "characters": doc.characters,
            "customSpells": doc.custom_spells,
        }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def save_document(doc: Document, path: str | Path | None = None) -> Path:
    path = Path(path) if path else doc.path
    if doc.kind == "character" and len(doc.characters) != 1:
        doc.kind = "backup"
    path.write_text(dumps_document(doc), encoding="utf-8")
    doc.path = path
    doc.dirty = False
    return path


def get_character(doc: Document, char_id: str | None) -> dict[str, Any] | None:
    if not doc.characters:
        return None
    if char_id:
        for char in doc.characters:
            if item_id(char) == char_id:
                return char
        for char in doc.characters:
            if norm_text(item_name(char)) == norm_text(char_id):
                return char
    return doc.characters[0]


def get_items(char: dict[str, Any] | None, category: Category) -> list[dict[str, Any]]:
    if char is None or category == "characters":
        return []
    field = CATEGORY_FIELD[category]
    return [_as_dict(x) for x in _as_list(char.get(field))]


def set_items(char: dict[str, Any], category: Category, items: list[dict[str, Any]]) -> None:
    char[CATEGORY_FIELD[category]] = items


def _name_key(category: Category) -> str:
    return "title" if category == "notes" else "name"


def _extra_for(category: Category, item: dict[str, Any] | None) -> str:
    if not item:
        return ""
    if category == "players":
        return player_extra(item)
    if category == "allies":
        return ally_extra(item)
    if category == "notes":
        return note_extra(item)
    return character_label(item)


def _label_for(category: Category, left: dict[str, Any] | None, right: dict[str, Any] | None) -> str:
    item = left or right or {}
    if category == "notes":
        return item_name(item, "title") or "Без названия"
    return item_name(item) or "Без имени"


def pair_items(
    left: list[dict[str, Any]],
    right: list[dict[str, Any]],
    *,
    name_key: str,
    prefer_name: bool = False,
) -> list[tuple[dict[str, Any] | None, dict[str, Any] | None]]:
    right_unused = list(range(len(right)))
    left_match: list[int | None] = [None] * len(left)

    def take_right(predicate) -> int | None:
        for pos, ri in enumerate(right_unused):
            if predicate(right[ri]):
                return right_unused.pop(pos)
        return None

    id_pass = lambda item, src: bool(item_id(src)) and item_id(item) == item_id(src)
    name_pass = lambda item, src: bool(item_name(src, name_key)) and norm_text(
        item_name(item, name_key)
    ) == norm_text(item_name(src, name_key))
    passes = [name_pass, id_pass] if prefer_name else [id_pass, name_pass]

    for predicate in passes:
        for li, src in enumerate(left):
            if left_match[li] is not None:
                continue
            taken = take_right(lambda item, s=src, p=predicate: p(item, s))
            if taken is not None:
                left_match[li] = taken

    pairs: list[tuple[dict[str, Any] | None, dict[str, Any] | None]] = []
    for li, src in enumerate(left):
        ri = left_match[li]
        pairs.append((src, right[ri] if ri is not None else None))
    for ri in right_unused:
        pairs.append((None, right[ri]))
    return pairs


def diff_lists(
    left: list[dict[str, Any]],
    right: list[dict[str, Any]],
    category: Category,
) -> list[DiffRow]:
    name_key = _name_key(category)
    prefer_name = category == "notes"
    rows: list[DiffRow] = []
    for litem, ritem in pair_items(left, right, name_key=name_key, prefer_name=prefer_name):
        if litem is not None and ritem is not None:
            status: Status = "same" if comparable(litem) == comparable(ritem) else "different"
        elif litem is not None:
            status = "left_only"
        else:
            status = "right_only"
        key_src = litem or ritem or {}
        key = item_id(key_src) or norm_text(item_name(key_src, name_key)) or f"row-{len(rows)}"
        extra_item = ritem if status == "right_only" else litem
        if status == "different":
            extra = " | ".join(x for x in (_extra_for(category, litem), _extra_for(category, ritem)) if x)
        else:
            extra = _extra_for(category, extra_item)
        rows.append(
            DiffRow(
                key=f"{key}#{len(rows)}",
                status=status,
                label=_label_for(category, litem, ritem),
                extra=extra,
                left=litem,
                right=ritem,
            )
        )
    return rows


def find_match_index(
    source: dict[str, Any],
    dest: list[dict[str, Any]],
    *,
    name_key: str,
    prefer_name: bool,
) -> int | None:
    sid = item_id(source)
    sname = norm_text(item_name(source, name_key))
    name_check = lambda item: bool(sname) and norm_text(item_name(item, name_key)) == sname
    id_check = lambda item: bool(sid) and item_id(item) == sid
    checks = [name_check, id_check] if prefer_name else [id_check, name_check]
    for check in checks:
        for i, item in enumerate(dest):
            if check(item):
                return i
    return None


def copy_items(
    source_items: list[dict[str, Any]],
    dest_items: list[dict[str, Any]],
    *,
    name_key: str,
    prefer_name: bool = False,
) -> list[dict[str, Any]]:
    dest = [copy.deepcopy(x) for x in dest_items]
    for src in source_items:
        incoming = copy.deepcopy(src)
        idx = find_match_index(src, dest, name_key=name_key, prefer_name=prefer_name)
        if idx is None:
            dest.append(incoming)
            continue
        kept_id = item_id(dest[idx])
        dest[idx] = incoming
        if kept_id:
            dest[idx]["id"] = kept_id
    return dest


AVATAR_KEYS = ("avatarUrl", "avatar", "avatarOriginalUrl")


def new_character_id() -> str:
    return str(uuid.uuid4())


def reassign_character_id(char: dict[str, Any], new_id: str | None = None) -> str:
    """Give a hero a fresh id so MyChar import does not hit the old slot."""
    old = item_id(char)
    new_id = new_id or new_character_id()
    char["id"] = new_id
    if old:
        for key in AVATAR_KEYS:
            val = char.get(key)
            if isinstance(val, str) and old in val:
                char[key] = val.replace(old, new_id)
    return new_id


def copy_characters(
    sources: list[dict[str, Any]],
    dest_chars: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    dest = [copy.deepcopy(x) for x in dest_chars]
    for src in sources:
        incoming = copy.deepcopy(src)
        reassign_character_id(incoming)
        idx = find_match_index(src, dest, name_key="name", prefer_name=False)
        if idx is None:
            dest.append(incoming)
        else:
            dest[idx] = incoming
    return dest
