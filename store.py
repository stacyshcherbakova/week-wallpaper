"""Persist personal to-dos per week in data/todos.json.

JSON shape:  { "<monday-iso>": { "<0-6>": [ {"text": ..., "done": ...}, ... ] },
               "backlog": [ {"text": ..., "done": ...}, ... ] }

"backlog" is the week-independent "someday" list: it appears at the bottom of
every wallpaper until you delete the line.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from render import Todo

STORE = Path(__file__).parent / "data" / "todos.json"
CONFIG = Path(__file__).parent / "data" / "config.json"


def load_all() -> dict:
    if STORE.exists():
        try:
            return json.loads(STORE.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def save_all(data: dict) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def get_week(monday: dt.date) -> dict[int, list[Todo]]:
    week = load_all().get(monday.isoformat(), {})
    return {int(k): [Todo(**t) for t in v] for k, v in week.items()}


def set_week(monday: dt.date, todos_by_day: dict[int, list[Todo]]) -> None:
    data = load_all()
    packed = {
        str(i): [{"text": t.text, "done": t.done} for t in todos]
        for i, todos in todos_by_day.items() if todos
    }
    if packed:
        data[monday.isoformat()] = packed
    else:
        data.pop(monday.isoformat(), None)
    save_all(data)


BACKLOG_KEY = "backlog"


def get_backlog() -> list[Todo]:
    """Low-priority to-dos kept on every week's wallpaper."""
    return [Todo(**t) for t in load_all().get(BACKLOG_KEY, [])]


def set_backlog(todos: list[Todo]) -> None:
    data = load_all()
    packed = [{"text": t.text, "done": t.done} for t in todos]
    if packed:
        data[BACKLOG_KEY] = packed
    else:
        data.pop(BACKLOG_KEY, None)
    save_all(data)


# --- app config (e.g. which calendars count as meetings) ---
def load_config() -> dict:
    if CONFIG.exists():
        try:
            return json.loads(CONFIG.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def save_config(cfg: dict) -> None:
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))


def get_selected_calendars() -> list[str] | None:
    """None means 'not chosen yet' (default to all)."""
    return load_config().get("calendars")


def set_selected_calendars(names: list[str]) -> None:
    cfg = load_config()
    cfg["calendars"] = names
    save_config(cfg)


def clear_selected_calendars() -> None:
    """Back to the default: pull every calendar."""
    cfg = load_config()
    cfg.pop("calendars", None)
    save_config(cfg)


def get_theme() -> str | None:
    """Saved design preset name (None until the user picks one)."""
    return load_config().get("theme")


def set_theme(name: str) -> None:
    cfg = load_config()
    cfg["theme"] = name
    save_config(cfg)


# --- plain-text <-> todos (one to-do per line; prefix "x " marks it done) ---
def todos_to_text(todos: list[Todo]) -> str:
    return "\n".join((("x " if t.done else "") + t.text) for t in todos)


def text_to_todos(text: str) -> list[Todo]:
    out: list[Todo] = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        done = False
        if s[:2].lower() == "x ":
            done, s = True, s[2:].strip()
        elif s[:3] in ("[x]", "[X]"):
            done, s = True, s[3:].strip()
        if s:
            out.append(Todo(text=s, done=done))
    return out
