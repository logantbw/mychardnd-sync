import copy
import json
import tempfile
import unittest
from pathlib import Path

from sync_core import (
    copy_characters,
    copy_items,
    diff_lists,
    dumps_document,
    get_items,
    load_document,
    parse_document,
    reassign_character_id,
    set_items,
)


SAMPLE_CHAR = {
    "id": "char-sareya",
    "name": "Сарея Ваэль",
    "class": "Warlock",
    "level": 2,
    "players": [
        {"id": "p1", "name": "Ризен", "race": "Дроу", "className": "Чародей", "relation": "ally"},
        {"id": "p2", "name": "Эмбер Тлеющий", "race": "Человек", "className": "Монах", "relation": "ally"},
    ],
    "allies": [
        {"id": "a1", "name": "Дерек", "relation": "ally", "location": "", "note": "проклят"},
        {"id": "a2", "name": "Эльвира", "relation": "enemy", "location": "Дроу", "note": "начальница"},
    ],
    "customNotes": [
        {"id": "1", "title": "Заметки", "content": "", "collapsed": True},
        {"id": "2", "title": "Квесты", "content": "Найти выход"},
    ],
}

SAMPLE_OTHER = {
    "id": "char-ember",
    "name": "Эмбер Тлеющий",
    "class": "Monk",
    "level": 2,
    "players": [
        {"id": "px", "name": "Ризен", "race": "Дроу", "className": "Чародей", "relation": "ally"},
        {"id": "p3", "name": "Астра", "race": "Эльф", "className": "Волшебник", "relation": "ally"},
    ],
    "allies": [
        {"id": "a1", "name": "Дерек", "relation": "ally", "location": "", "note": "проклят магом"},
        {"id": "a9", "name": "Стул", "relation": "neutral", "location": "Микониды", "note": "душка"},
    ],
    "customNotes": [
        {"id": "99", "title": "Квесты", "content": "Найти выход\nПомочь гномке"},
        {"id": "1", "title": "Заметки", "content": "личное"},
    ],
}


class ParseTests(unittest.TestCase):
    def test_parse_character(self):
        doc = parse_document(SAMPLE_CHAR, "s.json")
        self.assertEqual(doc.kind, "character")
        self.assertEqual(len(doc.characters), 1)
        self.assertEqual(doc.characters[0]["name"], "Сарея Ваэль")

    def test_parse_backup(self):
        payload = {
            "format": "grimoire_backup_v1",
            "characters": [SAMPLE_CHAR, SAMPLE_OTHER],
            "customSpells": [{"id": "x"}],
            "theme": "dark",
        }
        doc = parse_document(payload, "b.json")
        self.assertEqual(doc.kind, "backup")
        self.assertEqual(len(doc.characters), 2)
        self.assertEqual(doc.custom_spells[0]["id"], "x")

    def test_parse_array(self):
        doc = parse_document([SAMPLE_CHAR], "a.json")
        self.assertEqual(doc.kind, "backup")
        self.assertEqual(len(doc.characters), 1)

    def test_roundtrip_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.json"
            path.write_text(json.dumps(SAMPLE_CHAR, ensure_ascii=False), encoding="utf-8")
            doc = load_document(path)
            again = json.loads(dumps_document(doc))
            self.assertEqual(again["name"], "Сарея Ваэль")
            self.assertEqual(len(again["players"]), 2)

    def test_load_real_sareya_export(self):
        path = Path(r"F:\Documents\dnd\Сарея_Ваэль_MyChar_DnD2.json")
        if not path.exists():
            self.skipTest("sample export not on this machine")
        doc = load_document(path)
        char = doc.characters[0]
        self.assertEqual(char["name"], "Сарея Ваэль")
        self.assertGreaterEqual(len(get_items(char, "players")), 1)
        self.assertGreaterEqual(len(get_items(char, "allies")), 1)
        self.assertGreaterEqual(len(get_items(char, "notes")), 1)


class DiffTests(unittest.TestCase):
    def test_players_match_by_name(self):
        rows = diff_lists(SAMPLE_CHAR["players"], SAMPLE_OTHER["players"], "players")
        by_label = {r.label: r for r in rows}
        self.assertEqual(by_label["Ризен"].status, "same")
        self.assertEqual(by_label["Эмбер Тлеющий"].status, "left_only")
        self.assertEqual(by_label["Астра"].status, "right_only")

    def test_allies_different_note(self):
        rows = diff_lists(SAMPLE_CHAR["allies"], SAMPLE_OTHER["allies"], "allies")
        derek = next(r for r in rows if r.label == "Дерек")
        self.assertEqual(derek.status, "different")
        chair = next(r for r in rows if r.label == "Стул")
        self.assertEqual(chair.status, "right_only")

    def test_notes_match_by_title(self):
        rows = diff_lists(SAMPLE_CHAR["customNotes"], SAMPLE_OTHER["customNotes"], "notes")
        quests = next(r for r in rows if r.label == "Квесты")
        notes = next(r for r in rows if r.label == "Заметки")
        self.assertEqual(quests.status, "different")
        self.assertEqual(notes.status, "different")


class CopyTests(unittest.TestCase):
    def test_copy_player_keeps_dest_id(self):
        dest = copy.deepcopy(SAMPLE_OTHER["players"])
        updated = copy_items([SAMPLE_CHAR["players"][0]], dest, name_key="name")
        risen = next(p for p in updated if p["name"] == "Ризен")
        self.assertEqual(risen["id"], "px")
        self.assertIn("Астра", [p["name"] for p in updated])

    def test_copy_missing_ally_appends(self):
        updated = copy_items(
            [SAMPLE_OTHER["allies"][1]],
            SAMPLE_CHAR["allies"],
            name_key="name",
        )
        self.assertEqual(len(updated), 3)
        self.assertEqual(updated[-1]["name"], "Стул")

    def test_copy_note_by_title(self):
        updated = copy_items(
            [SAMPLE_OTHER["customNotes"][0]],
            SAMPLE_CHAR["customNotes"],
            name_key="title",
            prefer_name=True,
        )
        quests = next(n for n in updated if n["title"] == "Квесты")
        self.assertIn("гномке", quests["content"])
        self.assertEqual(quests["id"], "2")

    def test_copy_character_into_backup(self):
        updated = copy_characters([SAMPLE_OTHER], [dict(SAMPLE_CHAR)])
        self.assertEqual(len(updated), 2)
        self.assertEqual(updated[1]["name"], "Эмбер Тлеющий")
        self.assertNotEqual(updated[1]["id"], SAMPLE_OTHER["id"])
        self.assertEqual(updated[0]["id"], SAMPLE_CHAR["id"])

    def test_copy_character_replaces_same_name_with_new_id(self):
        clone = dict(SAMPLE_CHAR)
        clone["level"] = 9
        updated = copy_characters([clone], [dict(SAMPLE_CHAR)])
        self.assertEqual(len(updated), 1)
        self.assertEqual(updated[0]["level"], 9)
        self.assertNotEqual(updated[0]["id"], SAMPLE_CHAR["id"])

    def test_reassign_rewrites_avatar_keys(self):
        char = {
            "id": "abc-old",
            "name": "Сарея",
            "avatarUrl": "char_avatar__abc-old",
            "avatar": "char_avatar__abc-old",
            "avatarOriginalUrl": "char_avatar__abc-old_original",
        }
        new_id = reassign_character_id(char)
        self.assertEqual(char["id"], new_id)
        self.assertNotEqual(new_id, "abc-old")
        self.assertEqual(char["avatarUrl"], f"char_avatar__{new_id}")
        self.assertEqual(char["avatar"], f"char_avatar__{new_id}")
        self.assertEqual(char["avatarOriginalUrl"], f"char_avatar__{new_id}_original")

    def test_set_items_on_character(self):
        char = dict(SAMPLE_CHAR)
        set_items(char, "notes", [{"id": "1", "title": "Квесты", "content": "x"}])
        self.assertEqual(get_items(char, "notes")[0]["content"], "x")


if __name__ == "__main__":
    unittest.main()
