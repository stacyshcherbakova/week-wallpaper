"""Weekly Wallpaper — plan your week, generate a Mac wallpaper, set it.

Run:  streamlit run app.py   (or double-click run.command)
"""
from __future__ import annotations

import datetime as dt
import hashlib
import io
from pathlib import Path

import streamlit as st

import calendar_sync
import store
import wallpaper
from render import THEMES, Theme, Week, render_week

HERE = Path(__file__).parent
OUT = HERE / "out"
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def monday_of(d: dt.date) -> dt.date:
    return d - dt.timedelta(days=d.weekday())


st.set_page_config(page_title="Weekly Wallpaper", page_icon="🗓️", layout="wide")

# --------------------------------------------------------------------------- #
# Header / controls — everything lives in one row so the day columns below
# get the full page height for writing to-dos.
# --------------------------------------------------------------------------- #
st.title("🗓️ Weekly Wallpaper")

c_date, c_theme, c_sync, c_cal, c_help = st.columns([2, 1, 1, 1, 1])
with c_date:
    picked = st.date_input("Week of", value=monday_of(dt.date.today()))
monday = monday_of(picked)
sunday = monday + dt.timedelta(days=6)
key = monday.isoformat()
st.caption(f"Planning **{monday:%a %d %b} – {sunday:%a %d %b %Y}**")

with c_theme:
    names = list(THEMES)
    saved = store.get_theme()
    design = st.selectbox("Design", names,
                          index=names.index(saved) if saved in names else 0)
    if design != saved:
        store.set_theme(design)
THEME = Theme(**THEMES[design])

with c_cal:
    st.write("")
    with st.popover("📅 Calendars", use_container_width=True):
        hdr, refresh = st.columns([4, 1])
        hdr.markdown("**Which calendars sync**")
        if refresh.button("↻", help="Reload the calendar list from macOS"):
            st.session_state.pop("all_cals", None)

        # cache the (deduped) calendar list so we don't re-shell icalBuddy each rerun
        if "all_cals" not in st.session_state:
            st.session_state["all_cals"] = calendar_sync.list_calendars()
        all_cals = st.session_state["all_cals"]

        stored = store.get_selected_calendars()       # None => all calendars
        st.session_state["selected_cals"] = stored     # None => Sync pulls everything

        if stored is None:
            st.caption("Syncing **all** your Apple Calendar events.")
        else:
            st.caption(f"Syncing **{len(stored)}** selected calendar(s).")

        # optional — most people can ignore this and get everything
        if not all_cals:
            st.caption("No calendars found. Add an account in **System Settings → "
                       "Internet Accounts** (no Apple ID needed), then hit ↻.")
        else:
            with st.form("cal_form"):
                picked_cals = st.multiselect(
                    "Calendars", all_cals,
                    default=[c for c in (stored or all_cals) if c in all_cals],
                    label_visibility="collapsed", placeholder="Choose calendars")
                b1, b2 = st.columns(2)
                if b1.form_submit_button("Save", use_container_width=True):
                    store.set_selected_calendars(picked_cals)
                    st.session_state["selected_cals"] = picked_cals
                    st.toast(f"Using {len(picked_cals)} calendar(s)", icon="✅")
                if b2.form_submit_button("Use all", use_container_width=True):
                    store.clear_selected_calendars()
                    st.session_state["selected_cals"] = None
                    st.toast("Using all calendars", icon="✅")

with c_help:
    st.write("")
    with st.popover("ℹ️ How it works", use_container_width=True):
        st.markdown(
            "1. Pick the week (starts Monday). Meetings load **automatically** from "
            "Apple Calendar (hit **Refresh** to re-pull).\n"
            "2. Type personal **to-dos** under each day — one per line. "
            "Prefix a line with `x ` to mark it done.\n"
            "3. The preview redraws as you type — hit **Set as wallpaper** "
            "when it looks right.\n\n"
            "To-dos save themselves per week in `data/todos.json`."
        )
        st.caption(
            "First time you Set as wallpaper, macOS may ask permission for your "
            "terminal to control **System Events** — click *OK*."
        )

with c_sync:
    st.write("")
    if st.button("🔄 Refresh from Calendar", use_container_width=True):
        if not calendar_sync.icalbuddy_available():
            st.error("icalBuddy not installed. Run: `brew install ical-buddy`")
        else:
            cals = st.session_state.get("selected_cals")
            try:
                m = calendar_sync.fetch_week_meetings(monday, include=cals)
                st.session_state.setdefault("meetings", {})[key] = m
                total = sum(len(v) for v in m.values())
                if total:
                    st.session_state["sync_feedback"] = (
                        key, "success", f"✅ Synced {total} event(s) for this week.")
                else:
                    nxt = calendar_sync.next_event_date(monday, include=cals)
                    if nxt:
                        st.session_state["sync_feedback"] = (
                            key, "info",
                            f"Synced ✓ — no events Mon {monday:%d %b} – Sun {sunday:%d %b}. "
                            f"Your next event is **{nxt:%a %d %b %Y}** — open that week to see it.")
                    else:
                        st.session_state["sync_feedback"] = (
                            key, "info", "Synced ✓ — no events found in the next 6 months.")
            except calendar_sync.CalendarError as e:
                st.session_state["sync_feedback"] = (key, "error", f"Calendar sync failed: {e}")

# Auto-load this week's meetings once, so they appear in the columns AND the
# preview without needing to click Refresh first. Refresh re-pulls (below).
meetings_cache = st.session_state.setdefault("meetings", {})
if key not in meetings_cache:
    try:
        meetings_cache[key] = calendar_sync.fetch_week_meetings(
            monday, include=st.session_state.get("selected_cals"))
    except calendar_sync.CalendarError:
        meetings_cache[key] = {i: [] for i in range(7)}
meetings = meetings_cache[key]

fb = st.session_state.get("sync_feedback")
if fb and fb[0] == key:
    getattr(st, fb[1])(fb[2])

# --------------------------------------------------------------------------- #
# Per-day editors
# --------------------------------------------------------------------------- #
week_todos = store.get_week(monday)
new_todos: dict[int, list] = {}
cols = st.columns(7)
for i, col in enumerate(cols):
    with col:
        d = monday + dt.timedelta(days=i)
        weekend = " 🟠" if i >= 5 else ""
        st.markdown(f"**{DAYS[i]}** · {d.day}{weekend}")

        ms = meetings.get(i, [])
        if ms:
            st.caption("  \n".join(
                (f"`{m.time}` " if m.time else "`all-day` ") + m.title for m in ms))
        else:
            st.caption("_no meetings_")

        wkey = f"td_{key}_{i}"
        if wkey not in st.session_state:
            st.session_state[wkey] = store.todos_to_text(week_todos.get(i, []))
        st.text_area(
            DAYS[i], key=wkey, height=260, label_visibility="collapsed",
            placeholder="one to-do per line\nprefix 'x ' if done",
        )
        new_todos[i] = store.text_to_todos(st.session_state[wkey])

# --------------------------------------------------------------------------- #
# Live preview / set
# --------------------------------------------------------------------------- #
def render_png() -> bytes:
    week = Week.build(monday, meetings, new_todos)
    buf = io.BytesIO()
    render_week(week, THEME, today=dt.date.today()).save(buf, format="PNG")
    return buf.getvalue()


def save_png(data: bytes) -> str:
    """Write the render to a content-addressed path and return it.

    The hash in the filename is load-bearing, not tidiness: macOS caches the
    desktop picture *by path*, so re-setting a path it already holds leaves the
    previously decoded image on screen no matter how new the file is. A fresh
    path per distinct render forces it to re-read.
    """
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"wallpaper-{key}-{hashlib.sha1(data).hexdigest()[:10]}.png"
    if not path.exists():
        path.write_bytes(data)
    (OUT / "wallpaper.png").write_bytes(data)     # stable copy for the README

    # Keep the newest few renders; never touch the one we're about to set.
    stale = sorted((p for p in OUT.glob("wallpaper-*-*.png") if p != path),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    for old in stale[4:]:
        old.unlink(missing_ok=True)
    return str(path)


st.divider()

# To-dos autosave and the preview redraws every rerun (~0.5s — the calendar
# pull is cached in session state), so the image below is always current.
# The button's only job is pushing it to the desktop.
store.set_week(monday, new_todos)
png = render_png()

b1, b2, _ = st.columns([1, 1, 2])
if b1.button("🖥️  Set as wallpaper", type="primary", use_container_width=True):
    try:
        wallpaper.set_wallpaper(save_png(png))
        st.success("✅ Wallpaper updated — enjoy your week!")
    except wallpaper.WallpaperError as e:
        st.error(f"Couldn't set wallpaper: {e}")
b2.download_button("⬇️  Download PNG", png, file_name=f"week-{key}.png",
                   mime="image/png", use_container_width=True)

st.image(png, caption=f"Preview · {THEME.width} × {THEME.height} · redraws as you type",
         use_container_width=True)
