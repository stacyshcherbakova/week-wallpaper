"""Render a weekly-plan wallpaper as a PNG — "amber phosphor schedule".

A violet-CRT status board: seven day columns under a DIN-Condensed masthead,
monospaced times, today washed in accent, and a faint scanline/vignette
phosphor texture.

Nothing is ever hidden. Long titles wrap inside their column, and if a week is
busy enough to overflow, the type scales down (`fit_scale`) rather than
collapsing items into a "+N more".

Runnable standalone for a quick design preview:

    python render.py            # writes out/wallpaper.png with sample data

Layout / colour / type live in the Theme dataclass.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).parent
FONTS = "/System/Library/Fonts"
SUPP = "/System/Library/Fonts/Supplemental"
DIN_PATH = f"{SUPP}/DIN Condensed Bold.ttf"
MENLO_PATH = f"{FONTS}/Menlo.ttc"
SF_PATH = f"{FONTS}/SFNS.ttf"
HELV_PATH = f"{FONTS}/HelveticaNeue.ttc"


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #
@dataclass
class Meeting:
    time: str          # "10:00", or "" for an all-day event
    title: str


@dataclass
class Todo:
    text: str
    done: bool = False


@dataclass
class Day:
    date: dt.date
    meetings: list[Meeting] = field(default_factory=list)
    todos: list[Todo] = field(default_factory=list)


@dataclass
class Week:
    start: dt.date                     # the Monday
    days: list[Day]

    @classmethod
    def build(cls, monday: dt.date, meetings_by_day=None, todos_by_day=None) -> "Week":
        meetings_by_day = meetings_by_day or {}
        todos_by_day = todos_by_day or {}
        days = [
            Day(date=monday + dt.timedelta(days=i),
                meetings=list(meetings_by_day.get(i, [])),
                todos=list(todos_by_day.get(i, [])))
            for i in range(7)
        ]
        return cls(start=monday, days=days)


# --------------------------------------------------------------------------- #
# Theme
# --------------------------------------------------------------------------- #
@dataclass
class Theme:
    # The design lives on a 3024×1964 canvas; `scale` multiplies every pixel
    # dimension at construction, so scale=2 renders the identical layout as a
    # 6048×3928 PNG. Hardcoded offsets in the drawing code go through `px()`.
    scale: float = 2.0

    width: int = 3024
    height: int = 1964

    # palette — violet phosphor on deep plum-black
    ink: str = "#0A0810"          # deep plum-black
    ink_hi: str = "#181022"       # violet bloom colour
    accent: str = "#B98CFF"       # primary phosphor (violet)
    accent_dim: str = "#8A6DC2"   # secondary accent (orchid)
    parch: str = "#EAE6F2"        # cool lilac-white (titles)
    stone: str = "#847C97"        # muted violet-grey (secondary text)
    stone_dim: str = "#524B63"    # faint labels / empty ticks
    line: str = "#271F38"         # violet hairline

    scanline_alpha: int = 9       # 0 disables the CRT scanlines
    vignette: float = 0.34        # edge darkening strength

    # layout — one column per day, nothing is ever truncated
    margin_x: int = 120
    margin_top: int = 310         # 14" panel is 100 px/cm, so this is ~3.1 cm
    margin_bottom: int = 110
    header_h: int = 230
    col_gap: int = 26             # gutter between day columns
    right_margin: int = 0         # clear band on the right (for desktop icons)
    day_head_h: int = 152         # day name + date block atop each column
    sec_gap: int = 30             # meetings -> tasks divider spacing
    time_w: int = 86              # gutter holding the time / checkbox
    line_h: int = 44
    min_scale: float = 0.62       # auto-fit floor before we accept clipping
    max_scale: float = 1.12       # auto-fit ceiling; higher just wraps more
    show_load: bool = False       # per-day "load meter" ticks under the date

    # type sizes
    fs_eyebrow: int = 27
    fs_title: int = 132
    fs_meta: int = 27
    fs_collabel: int = 22
    fs_day: int = 64
    fs_date: int = 26
    fs_time: int = 26
    fs_body: int = 30

    _SCALED = ("width", "height", "margin_x", "margin_top", "margin_bottom",
               "header_h", "col_gap", "right_margin", "day_head_h", "sec_gap",
               "time_w", "line_h", "fs_eyebrow", "fs_title", "fs_meta",
               "fs_collabel", "fs_day", "fs_date", "fs_time", "fs_body")

    def __post_init__(self):
        if self.scale != 1:
            for f in self._SCALED:
                setattr(self, f, round(getattr(self, f) * self.scale))

    def px(self, n: float) -> float:
        """Scale a hardcoded design-space offset to output pixels."""
        return n * self.scale

    def lw(self, n: float) -> int:
        """Line width in output pixels (never thinner than 1)."""
        return max(1, round(n * self.scale))


DAY_ABBR = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
          "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


# --------------------------------------------------------------------------- #
# Fonts
# --------------------------------------------------------------------------- #
_SF_FALLBACK = {"Regular": 0, "Bold": 1, "Medium": 4, "Semibold": 4}


@lru_cache(maxsize=None)
def din(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(DIN_PATH, size)


@lru_cache(maxsize=None)
def mono(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(MENLO_PATH, size, index=1 if bold else 0)


@lru_cache(maxsize=None)
def sf(size: int, weight: str = "Regular") -> ImageFont.FreeTypeFont:
    try:
        f = ImageFont.truetype(SF_PATH, size)
        try:
            f.set_variation_by_name(weight)
        except Exception:
            pass
        return f
    except Exception:
        return ImageFont.truetype(HELV_PATH, size, index=_SF_FALLBACK.get(weight, 0))


# --------------------------------------------------------------------------- #
# Colour helpers
# --------------------------------------------------------------------------- #
def hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def lerp(a, b, t: float):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def draw_ls(draw, xy, text, fnt, fill, ls=0, anchor="la"):
    """Letter-spaced text (anchor applies per-glyph baseline via 'a'/'s')."""
    if ls == 0:
        draw.text(xy, text, font=fnt, fill=fill, anchor=anchor)
        return draw.textlength(text, font=fnt)
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=fnt, fill=fill, anchor=anchor)
        x += draw.textlength(ch, font=fnt) + ls
    return x - xy[0] - ls if text else 0


def wrap(draw, text, fnt, max_w) -> list[str]:
    """Greedy word wrap, breaking inside a word only when it can't fit alone."""
    words = text.split()
    if not words:
        return [""]
    lines, cur = [], words[0]
    for w in words[1:]:
        trial = f"{cur} {w}"
        if draw.textlength(trial, font=fnt) <= max_w:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)

    out = []
    for ln in lines:
        while draw.textlength(ln, font=fnt) > max_w and len(ln) > 1:
            cut = len(ln)
            while cut > 1 and draw.textlength(ln[:cut], font=fnt) > max_w:
                cut -= 1
            out.append(ln[:cut])
            ln = ln[cut:]
        out.append(ln)
    return out


# --------------------------------------------------------------------------- #
# Geometry
# --------------------------------------------------------------------------- #
def _geometry(th: Theme):
    grid_top = th.margin_top + th.header_h
    grid_bottom = th.height - th.margin_bottom
    grid_right = th.width - th.margin_x - th.right_margin
    col_w = (grid_right - th.margin_x - 6 * th.col_gap) / 7
    return dict(grid_top=grid_top, grid_bottom=grid_bottom,
                grid_right=grid_right, col_w=col_w,
                body_top=grid_top + th.day_head_h,
                body_h=grid_bottom - (grid_top + th.day_head_h))


def col_x(th: Theme, geo, i: int) -> float:
    return th.margin_x + i * (geo["col_w"] + th.col_gap)


# --------------------------------------------------------------------------- #
# Background: warm gradient + bloom + vignette + scanlines
# --------------------------------------------------------------------------- #
def make_background(th: Theme, bloom_ys) -> Image.Image:
    ink, hi = hex_rgb(th.ink), hex_rgb(th.ink_hi)
    # subtle vertical warmth (top a touch warmer/lighter)
    strip = Image.new("RGB", (1, th.height))
    sp = strip.load()
    for y in range(th.height):
        sp[0, y] = lerp(hi, ink, min(1.0, (y / th.height) * 1.4))
    base = strip.resize((th.width, th.height)).convert("RGB")

    # amber bloom behind header + today lane
    bloom = Image.new("L", (th.width, th.height), 0)
    bd = ImageDraw.Draw(bloom)
    for (bx, by, br, strength) in bloom_ys:
        bd.ellipse([bx - br, by - br, bx + br, by + br], fill=int(255 * strength))
    bloom = bloom.filter(ImageFilter.GaussianBlur(th.width * 0.10))
    accent_layer = Image.new("RGB", (th.width, th.height), hex_rgb(th.accent))
    base = Image.composite(accent_layer, base, bloom.point(lambda v: int(v * 0.16)))

    # vignette
    if th.vignette > 0:
        vig = Image.new("L", (th.width, th.height), 0)
        vd = ImageDraw.Draw(vig)
        m = int(th.width * 0.14)
        vd.ellipse([m, m, th.width - m, th.height - m], fill=255)
        vig = vig.filter(ImageFilter.GaussianBlur(th.width * 0.09))
        dark = Image.new("RGB", (th.width, th.height), (0, 0, 0))
        base = Image.composite(base, dark, vig.point(lambda v: int(255 - (255 - v) * th.vignette)))

    # CRT scanlines
    if th.scanline_alpha > 0:
        over = Image.new("RGBA", (th.width, th.height), (0, 0, 0, 0))
        od = ImageDraw.Draw(over)
        a = th.scanline_alpha
        for y in range(0, th.height, max(1, round(th.px(3)))):
            od.line([(0, y), (th.width, y)], fill=(0, 0, 0, a), width=th.lw(1))
        base = Image.alpha_composite(base.convert("RGBA"), over).convert("RGB")

    return base


# --------------------------------------------------------------------------- #
# Columns
# --------------------------------------------------------------------------- #
def _metrics(th: Theme, s: float) -> dict:
    """Every size that scales together when we shrink to fit."""
    return dict(fs_body=max(12, round(th.fs_body * s)),
                fs_time=max(11, round(th.fs_time * s)),
                line_h=th.line_h * s,
                sec_gap=th.sec_gap * s,
                time_w=th.time_w * s)


def _day_blocks(draw, day: Day, m: dict, col_w: float):
    """Wrap a day's content. Returns (meetings, tasks, height_needed)."""
    body = sf(m["fs_body"])
    text_w = col_w - m["time_w"]
    meets = [(x, wrap(draw, x.title, body, text_w)) for x in day.meetings]
    tasks = [(t, wrap(draw, t.text, body, text_w)) for t in day.todos]
    n = sum(len(w) for _, w in meets) + sum(len(w) for _, w in tasks)
    h = max(n, 1) * m["line_h"] + (m["sec_gap"] if meets and tasks else 0)
    return meets, tasks, h


def fit_scale(draw, week: Week, th: Theme, geo) -> float:
    """Largest scale at which the busiest day still fits its column.

    Nothing is ever dropped. A packed week shrinks the type (to `min_scale`);
    a quiet one grows it (to `max_scale`) rather than leaving the board empty.
    """
    s = th.max_scale
    while s > th.min_scale:
        m = _metrics(th, s)
        if all(_day_blocks(draw, d, m, geo["col_w"])[2] <= geo["body_h"]
               for d in week.days):
            return s
        s -= 0.04
    return th.min_scale


def draw_column(draw, th, geo, i: int, day: Day, m: dict, is_today, is_weekend):
    C = {k: hex_rgb(getattr(th, k)) for k in
         ("accent", "accent_dim", "parch", "stone", "stone_dim", "line")}
    x = col_x(th, geo, i)
    col_w = geo["col_w"]
    body = sf(m["fs_body"])
    tick = mono(m["fs_time"])
    lh, tw = m["line_h"], m["time_w"]

    # --- day head ---
    day_col = C["accent"] if is_today else (C["stone"] if is_weekend else C["parch"])
    draw.text((x, geo["grid_top"]), DAY_ABBR[day.date.weekday()],
              font=din(th.fs_day), fill=day_col, anchor="la")
    draw.text((x + th.px(3), geo["grid_top"] + th.fs_day + th.px(14)),
              f"{MONTHS[day.date.month - 1]} {day.date.day:02d}",
              font=mono(th.fs_date),
              fill=C["accent_dim"] if is_today else C["stone"], anchor="la")
    # optional load meter — 6 ticks, filled = day's item count (busyness)
    if th.show_load:
        load = min(len(day.meetings) + len(day.todos), 6)
        ty = geo["grid_top"] + th.fs_day + th.px(54)
        for k in range(6):
            col = C["accent"] if k < load else C["stone_dim"]
            draw.rounded_rectangle([x + k * th.px(20), ty,
                                    x + k * th.px(20) + th.px(11), ty + th.px(15)],
                                   radius=th.px(3), fill=col)
    # rule under the head, brighter on today
    ry = geo["body_top"] - th.px(26)
    draw.line([(x, ry), (x + col_w, ry)],
              fill=C["accent"] if is_today else C["line"],
              width=th.lw(3) if is_today else th.lw(1))

    meets, tasks, _ = _day_blocks(draw, day, m, col_w)
    y = geo["body_top"]

    if not meets and not tasks:
        draw.text((x, y + lh / 2), "—", font=body, fill=C["stone_dim"], anchor="lm")
        return

    # --- meetings ---
    for mt, lines in meets:
        head_y = y + lh / 2
        for ln in lines:
            draw.text((x + tw, y + lh / 2), ln, font=body, fill=C["parch"], anchor="lm")
            y += lh
        if mt.time:
            draw.text((x + tw - th.px(12), head_y), mt.time, font=tick,
                      fill=C["accent"], anchor="rm")
        else:                                    # all-day: a filled pip
            draw.rounded_rectangle(
                [x + tw - th.px(30), head_y - th.px(7),
                 x + tw - th.px(14), head_y + th.px(7)],
                radius=th.px(4), fill=C["accent_dim"])

    if meets and tasks:
        y += m["sec_gap"] / 2
        draw.line([(x, y), (x + col_w * 0.5, y)], fill=C["line"], width=th.lw(1))
        y += m["sec_gap"] / 2

    # --- tasks ---
    for t, lines in tasks:
        head_y = y + lh / 2
        col = C["stone"] if t.done else C["parch"]
        for ln in lines:
            draw.text((x + tw, y + lh / 2), ln, font=body, fill=col, anchor="lm")
            if t.done:
                w = draw.textlength(ln, font=body)
                draw.line([(x + tw, y + lh / 2), (x + tw + w, y + lh / 2)],
                          fill=C["stone_dim"], width=th.lw(2))
            y += lh
        draw.text((x, head_y), "[×]" if t.done else "[ ]", font=tick,
                  fill=C["accent"] if t.done else C["accent_dim"], anchor="lm")


# --------------------------------------------------------------------------- #
# Header + compose
# --------------------------------------------------------------------------- #
def _range_label(start: dt.date) -> str:
    end = start + dt.timedelta(days=6)
    if start.month == end.month:
        return f"{MONTHS[start.month - 1]} {start.day} – {end.day}"
    return f"{MONTHS[start.month - 1]} {start.day} – {MONTHS[end.month - 1]} {end.day}"


def render_week(week: Week, theme: Theme | None = None, today: dt.date | None = None) -> Image.Image:
    th = theme or Theme()
    geo = _geometry(th)
    today = today or dt.date.today()

    # Measure first (textlength needs a draw, not a real canvas) so the type
    # scale and the column chrome can both follow the actual content.
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    m = _metrics(th, fit_scale(probe, week, th, geo))
    content_h = max(_day_blocks(probe, d, m, geo["col_w"])[2] for d in week.days)
    chrome_bottom = min(geo["grid_bottom"], geo["body_top"] + content_h + th.px(44))

    # bloom sources: header, and today's column if in view
    blooms = [(int(th.width * 0.24), int(th.margin_top * 0.4), int(th.width * 0.28), 0.9)]
    today_idx = next((i for i, d in enumerate(week.days) if d.date == today), None)
    if today_idx is not None:
        tx = col_x(th, geo, today_idx) + geo["col_w"] / 2
        blooms.append((int(tx), int((geo["grid_top"] + chrome_bottom) / 2),
                       int(th.width * 0.26), 0.8))

    img = make_background(th, blooms)

    # faint wash down today's column so the eye lands there first
    if today_idx is not None:
        over = Image.new("RGBA", (th.width, th.height), (0, 0, 0, 0))
        tx = col_x(th, geo, today_idx)
        ImageDraw.Draw(over).rounded_rectangle(
            [tx - th.px(18), geo["grid_top"] - th.px(34),
             tx + geo["col_w"] + th.px(18), chrome_bottom],
            radius=th.px(20), fill=hex_rgb(th.accent) + (15,))
        img = Image.alpha_composite(img.convert("RGBA"), over).convert("RGB")

    draw = ImageDraw.Draw(img)
    C = {k: hex_rgb(getattr(th, k)) for k in ("accent", "accent_dim", "parch", "stone", "stone_dim", "line")}

    # --- header ---
    wk = week.start.isocalendar().week
    n_meet = sum(len(d.meetings) for d in week.days)
    n_todo = sum(len(d.todos) for d in week.days)
    draw_ls(draw, (th.margin_x, th.margin_top), f"WEEK {wk:02d}  ·  {week.start.year}",
            mono(th.fs_eyebrow), C["accent_dim"], ls=th.px(7), anchor="ls")
    draw.text((th.margin_x - th.px(3), th.margin_top + th.px(150)), _range_label(week.start),
              font=din(th.fs_title), fill=C["parch"], anchor="ls")
    draw_ls(draw, (geo["grid_right"], th.margin_top + th.px(150)),
            f"{n_meet} MEETINGS   {n_todo} TASKS", mono(th.fs_meta), C["stone"],
            anchor="rs")

    # divider under header
    dy = geo["grid_top"] - th.px(62)
    draw.line([(th.margin_x, dy), (geo["grid_right"], dy)],
              fill=C["line"], width=th.lw(2))

    # --- columns ---
    for i, day in enumerate(week.days):
        if i > 0:                                # gutter hairline
            gx = col_x(th, geo, i) - th.col_gap / 2
            draw.line([(gx, geo["grid_top"] - th.px(34)), (gx, chrome_bottom)],
                      fill=C["line"], width=th.lw(1))
        draw_column(draw, th, geo, i, day, m,
                    is_today=(day.date == today), is_weekend=(i >= 5))

    return img


# --------------------------------------------------------------------------- #
# Sample data for standalone preview
# --------------------------------------------------------------------------- #
def _sample_week() -> Week:
    monday = dt.date(2026, 7, 20)
    meetings = {
        0: [Meeting("10:00", "Team standup"), Meeting("14:00", "1:1 with Alex"),
            Meeting("16:30", "Cluster capacity review")],
        1: [Meeting("09:30", "Sprint planning"), Meeting("13:00", "Vendor call — storage")],
        2: [Meeting("", "On-call all day"), Meeting("11:00", "Green Alma demo")],
        3: [Meeting("15:00", "HPC users office hours")],
        4: [Meeting("10:00", "Standup"), Meeting("12:00", "Lunch & learn: Slurm")],
        5: [],
        6: [Meeting("18:00", "Dinner with M.")],
    }
    todos = {
        0: [Todo("Submit ReFrame benchmark run"), Todo("Reply to storage ticket", done=True),
            Todo("Draft weekly report")],
        1: [Todo("Review PR #212"), Todo("Book flights")],
        2: [Todo("Patch login nodes"), Todo("Gym")],
        3: [Todo("Update wallpaper README"), Todo("Call dentist")],
        4: [Todo("Merge carbon-model branch"), Todo("Groceries")],
        5: [Todo("Hike"), Todo("Read big-clouds paper 2")],
        6: [Todo("Plan next week"), Todo("Meal prep")],
    }
    return Week.build(monday, meetings, todos)


def main():
    out = HERE / "out" / "wallpaper.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    render_week(_sample_week(), Theme(), today=dt.date(2026, 7, 22)).save(out)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
