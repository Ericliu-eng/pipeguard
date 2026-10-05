"""Render the README flow animation offline (requires Pillow).

One reported run walks through every path PipeGuard adds: API-key checks,
idempotent storage, a safe retry and a rejected conflicting one, the
pipeline's own checks, the row-count baseline from run history, the anomaly
that fails, the rule-based incident analysis, and the dashboard. It is an
illustration of the implemented behavior, not a recording. Thresholds and
messages follow the defaults in backend/pipeguard/config.py and the rules in
backend/pipeguard/services/.

Colors and layout match the flow animation of the companion Orbit project.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
W, H, FPS = 1200, 620, 24  # layout units; the output is ZOOM times larger
ZOOM = 1.5  # 1800x930: sharp on high-density screens
S = 3  # drawing scale, 2x the output: supersampling for smooth edges
OUT = round(W * ZOOM), round(H * ZOOM)
FADE_SECONDS = 0.3  # highlight transitions between beats

BG, PANEL, SOFT, LINE = "#f7f8fa", "#ffffff", "#f3f5f8", "#d9dee6"
TEXT, MUTED, DIM, WIRE = "#202735", "#626d7d", "#9aa4b2", "#b7c0cc"
ACCENT, GREEN, AMBER, RED = "#365ec9", "#26734d", "#94611d", "#b33b3b"
TINT = {ACCENT: "#eef3fd", GREEN: "#e9f4ee", AMBER: "#fbf3e6", RED: "#fbeeee"}
BAR = "#c9d4ec"

PIPELINE, DASHBOARD = (30, 110, 170, 140), (30, 270, 170, 150)
API = (235, 110, 255, 280)
QUALITY = (525, 110, 290, 280)
HISTORY = (850, 110, 320, 280)
DETAIL, ANALYSIS = (30, 440, 440, 95), (500, 440, 670, 95)
SLOT = {"pipeline": (115, 222), "api": (362, 362), "quality": (670, 362)}
RULES = [
    "key matches (constant time)",
    "same id, same data → 200",
    "same id, new data → 409",
    "new run → store + checks",
]
OWN_CHECKS = ["not_null", "unique", "freshness"]
HISTORY_ROWS = [500, 496, 503, 498, 503]  # mean 500.0
CURRENT_ROWS = 112
DROP = (500 - CURRENT_ROWS) / 500  # 77.6%, against the 30% default threshold

BEATS = [  # (caption, code line, explanation, seconds)
    (
        "A pipeline reports a finished run",
        "POST /runs  external_run_id=mkt-0928  X-API-Key",
        "It already ran; it sends timings, row count, and its own checks",
        2.8,
    ),
    (
        "The API authenticates and stores it",
        "compare_digest(key) · sha256(canonical report)",
        "An unset key fails closed (503); a wrong one gets 401",
        3.4,
    ),
    (
        "Retries are safe; conflicts are rejected",
        "same id + same data → 200 · new data → 409",
        "A unique index settles concurrent retries",
        4.4,
    ),
    (
        "The pipeline's own checks all pass",
        "not_null PASS · unique PASS · freshness PASS",
        "Every row that arrived is valid on its own",
        2.8,
    ),
    (
        "PipeGuard compares the run with its history",
        "baseline = mean(last 5 healthy runs) = 500.0",
        "Only the monitor keeps history a single run cannot see",
        3.0,
    ),
    (
        "The row count collapsed, so the anomaly fails",
        "(500.0 − 112) / 500.0 = 77.6% > 30%",
        "status stays SUCCESS; quality_status becomes FAIL",
        3.2,
    ),
    (
        "The analysis names the check that failed",
        "POST /runs/42/analyze  →  severity medium",
        "Advice for a volume drop, not a generic “check for nulls”",
        3.2,
    ),
    (
        "The dashboard keeps both states visible",
        "GET /runs/page?quality_status=FAIL",
        "KPIs and the page come from one query, so they agree",
        3.0,
    ),
]
HOLD_SECONDS = 3.0
FONTS = {}


def font(size, weight="regular"):
    key = size, weight
    if key not in FONTS:
        names = {
            "regular": ("segoeui.ttf", "DejaVuSans.ttf"),
            "bold": ("segoeuib.ttf", "DejaVuSans-Bold.ttf"),
            "mono": ("consola.ttf", "DejaVuSansMono.ttf"),
        }[weight]
        for path in (
            Path("C:/Windows/Fonts") / names[0],
            Path("/usr/share/fonts/truetype/dejavu") / names[1],
            Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
        ):
            if path.exists():
                FONTS[key] = ImageFont.truetype(str(path), size * S)
                break
        else:
            raise RuntimeError("Install Segoe UI, DejaVu, or Arial to render the animation.")
    return FONTS[key]


def ease(t):
    """Cubic ease-in-out: gentle start and stop for every movement."""
    t = min(1.0, max(0.0, t))
    return 4 * t**3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


def span(t, start, end):
    """Progress of t through [start, end], clamped to 0..1."""
    return min(1.0, max(0.0, (t - start) / (end - start)))


def lerp(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(2))


def mix(a, b, t):
    ca = [int(a[i : i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i : i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(ca, cb, strict=True))


def after(beat, t, at_beat, at_t):
    """True once the story has reached (at_beat, at_t)."""
    return (beat, t) >= (at_beat, at_t)


class Frame:
    def __init__(self):
        self.image = Image.new("RGB", (W * S, H * S), BG)
        self.d = ImageDraw.Draw(self.image)

    def rect(self, box, fill, outline=None, width=1, radius=10):
        x, y, w, h = box
        self.d.rounded_rectangle(
            (x * S, y * S, (x + w) * S, (y + h) * S),
            radius * S,
            fill=fill,
            outline=outline,
            width=width * S,
        )

    def text(self, x, y, value, size=16, fill=TEXT, weight="regular"):
        self.d.text((x * S, y * S), value, fill=fill, font=font(size, weight))

    def width(self, value, size, weight="regular"):
        return self.d.textlength(value, font=font(size, weight)) / S

    def line(self, points, fill=WIRE, width=2, dashed=False, phase=0.0):
        pts = [(x * S, y * S) for x, y in points]
        if not dashed:
            self.d.line(pts, fill=fill, width=width * S, joint="curve")
            return
        for a, b in zip(pts, pts[1:], strict=False):
            length = ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5
            step, dash = 12 * S, 6 * S
            d = -step + (phase % 1) * step
            while d < length:
                p, q = max(0, d), min(length, d + dash)
                if q > p:
                    self.d.line(
                        [lerp(a, b, p / length), lerp(a, b, q / length)], fill=fill, width=width * S
                    )
                d += step

    def arrow(self, x, y, direction, fill=WIRE):
        shapes = {
            "right": [(-8, -5), (0, 0), (-8, 5)],
            "up": [(-5, 8), (0, 0), (5, 8)],
            "left": [(8, -5), (0, 0), (8, 5)],
            "down": [(-5, -8), (0, 0), (5, -8)],
        }
        self.d.polygon([((x + dx) * S, (y + dy) * S) for dx, dy in shapes[direction]], fill=fill)

    def pill(self, x, y, label, color, size=11, filled=False, level=1.0):
        w = self.width(label, size, "bold") + 16
        fill = mix(BG, color, level) if filled else PANEL
        ink = mix(BG, PANEL, level) if filled else mix(PANEL, color, level)
        self.rect((x, y, w, size + 10), fill, mix(BG, color, level), 1, radius=(size + 10) // 2)
        self.text(x + 8, y + 3, label, size, ink, "bold")
        return w


def look(color):
    return (TINT[color], color, color) if color else (PANEL, LINE, ACCENT)


def blend_look(previous, current, k):
    return tuple(mix(x, y, k) for x, y in zip(look(previous), look(current), strict=True))


def node(f, box, title, detail="", tag=None, style=None, title_size=18):
    fill, border, tag_color = style or look(None)
    f.rect(box, fill, border, 2 if border != LINE else 1)
    x, y, _, _ = box
    if tag:
        f.text(x + 14, y + 11, tag, 11, tag_color, "bold")
    f.text(x + 14, y + (27 if tag else 11), title, title_size, TEXT, "bold")
    if detail:
        f.text(x + 14, y + (53 if tag else 37), detail, 13, MUTED)


def card(f, center, label, note, badge=None, color=ACCENT, note_color=MUTED):
    cx, cy = center
    f.rect((cx - 68, cy - 19, 140, 46), "#e3e8ef", radius=8)  # soft drop shadow
    f.rect((cx - 70, cy - 22, 140, 46), PANEL, color, 2, radius=8)
    f.text(cx - 59, cy - 17, label, 13, TEXT, "bold")
    f.text(cx - 59, cy + 3, note, 11, note_color, "mono")
    if badge:
        bw = f.width(badge, 9, "bold") + 10
        f.rect((cx + 60 - bw, cy - 14, bw, 14), color, radius=7)
        f.text(cx + 65 - bw, cy - 13, badge, 9, PANEL, "bold")


def highlights(beat, t, final=False):
    lit = dict.fromkeys(("pipeline", "api", "quality", "history", "dashboard", "analysis"))
    if final:
        lit.update(quality=RED, analysis=AMBER, dashboard=ACCENT)
        return lit
    if beat == 0:
        lit.update(pipeline=ACCENT if t < 0.5 else None, api=ACCENT if t > 0.3 else None)
    elif beat == 1:
        lit.update(api=ACCENT, quality=ACCENT if t > 0.75 else None)
    elif beat == 2:
        lit.update(
            pipeline=ACCENT if t < 0.1 or 0.47 < t < 0.6 else None,
            api=GREEN if 0.25 < t < 0.47 else (RED if t > 0.7 else ACCENT),
        )
    elif beat == 3:
        lit.update(quality=GREEN if t > 0.7 else ACCENT)
    elif beat == 4:
        lit.update(history=ACCENT, quality=ACCENT if t > 0.5 else None)
    elif beat == 5:
        lit.update(quality=RED if t > 0.45 else ACCENT, history=RED if t > 0.2 else ACCENT)
    elif beat == 6:
        lit.update(quality=RED if t < 0.3 else None, analysis=AMBER)
    else:
        lit.update(
            dashboard=ACCENT, api=ACCENT if t < 0.5 else None, analysis=AMBER if t > 0.5 else None
        )
    return lit


def rule_marks(beat, t):
    """For each ingest rule: None, or (word shown at the right, color, matched)."""
    marks = [None] * len(RULES)
    if beat == 1:
        if t > 0.1:
            marks[0] = ("ok", GREEN, False)
        if t > 0.3:
            marks[1] = ("no", DIM, False)
            marks[2] = ("no", DIM, False)
        if t > 0.5:
            marks[3] = ("match", ACCENT, True)
    elif beat == 2:
        if 0.18 < t < 0.47:
            marks[0] = ("ok", GREEN, False)
        if 0.25 < t < 0.47:
            marks[1] = ("200", GREEN, True)
        if t > 0.62:
            marks[0] = ("ok", GREEN, False)
        if t > 0.7:
            marks[1] = ("no", DIM, False)
            marks[2] = ("409", RED, True)
    return marks


def own_check_state(beat, t, i):
    return after(beat, t, 3, 0.15 + i * 0.22)


def draw_frame(beat, t, final=False):
    f = Frame()
    f.rect((30, 28, 5, 28), ACCENT, radius=2)
    f.text(46, 22, "PipeGuard", 28, TEXT, "bold")
    f.text(
        46 + f.width("PipeGuard", 28, "bold") + 14,
        33,
        "Run history, cross-run anomaly detection, and incidents explained by the failing check",
        16,
        MUTED,
    )
    tag = "ILLUSTRATED FLOW"
    f.text(1170 - f.width(tag, 11, "bold"), 36, tag, 11, DIM, "bold")

    k = ease(span(t, 0, FADE_SECONDS / BEATS[beat][3])) if beat and not final else 1.0
    now, before = highlights(beat, t, final), (highlights(beat - 1, 1.0) if beat else {})
    style = {key: blend_look(before.get(key), now.get(key), k) for key in now}

    # Wiring: solid = run data, dashed = reads and comparisons.
    f.line([(200, 160), (235, 160)])
    f.arrow(235, 160, "right")
    f.line([(490, 200), (525, 200)])
    f.arrow(525, 200, "right")
    f.line([(815, 200), (850, 200)])
    f.arrow(850, 200, "right")
    comparing = beat in (4, 5) and not final
    f.line([(850, 300), (815, 300)], ACCENT if comparing else WIRE, 2, True, t * 4)
    f.arrow(815, 300, "left", ACCENT if comparing else WIRE)
    reading = now["dashboard"] is not None
    f.line([(200, 345), (235, 345)], ACCENT if reading else WIRE, 2, True, -t * 4)
    f.arrow(235, 345, "right", ACCENT if reading else WIRE)
    explaining = now["analysis"] is not None
    f.line([(670, 390), (670, 440)], AMBER if explaining else WIRE, 2, True, t * 4)
    f.arrow(670, 440, "down", AMBER if explaining else WIRE)

    node(f, PIPELINE, "de-lakehouse", "market-data run", "PIPELINE", style=style["pipeline"])

    # API: ingest rules, evaluated top to bottom.
    node(
        f,
        API,
        "FastAPI · POST /runs",
        "API key · fingerprint · unique index",
        "API",
        style=style["api"],
    )
    f.text(API[0] + 14, API[1] + 86, "INGEST, IN ORDER", 10, MUTED, "bold")
    for i, (rule, mark) in enumerate(
        zip(RULES, rule_marks(beat, t) if not final else [None] * 4, strict=True)
    ):
        y = API[1] + 106 + i * 26
        word, color, matched = mark or (None, None, False)
        if matched:
            f.rect((API[0] + 10, y - 3, API[2] - 20, 23), TINT[color], color, 1, radius=6)
        f.text(API[0] + 18, y, f"{i + 1}  {rule}", 13, color if matched else TEXT)
        if word:
            f.text(API[0] + API[2] - 18 - f.width(word, 11, "bold"), y + 1, word, 11, color, "bold")

    # Quality engine: the pipeline's checks, then the one only PipeGuard can run.
    node(
        f,
        QUALITY,
        "Checks",
        "one batch vs. its run history",
        "QUALITY ENGINE",
        style=style["quality"],
    )
    right = QUALITY[0] + QUALITY[2] - 14
    f.text(QUALITY[0] + 14, QUALITY[1] + 80, "REPORTED BY THE PIPELINE", 10, MUTED, "bold")
    for i, name in enumerate(OWN_CHECKS):
        y = QUALITY[1] + 98 + i * 23
        passed = final or own_check_state(beat, t, i)
        f.text(QUALITY[0] + 14, y, name, 12, TEXT if passed else DIM, "mono")
        label = "PASS" if passed else "…"
        f.pill(right - f.width(label, 10, "bold") - 16, y - 2, label, GREEN if passed else DIM, 10)
    f.text(QUALITY[0] + 14, QUALITY[1] + 168, "ADDED BY PIPEGUARD", 10, MUTED, "bold")
    y = QUALITY[1] + 186
    failed = final or after(beat, t, 5, 0.45)
    f.text(QUALITY[0] + 14, y, "row_count_anomaly", 12, RED if failed else TEXT, "mono")
    label = "FAIL" if failed else "…"
    f.pill(
        right - f.width(label, 10, "bold") - 16,
        y - 2,
        label,
        RED if failed else DIM,
        10,
        filled=failed,
    )
    if failed:
        level = 1.0 if final or beat > 5 else ease(span(t, 0.45, 0.65))
        f.text(
            QUALITY[0] + 14,
            y + 20,
            f"{CURRENT_ROWS} rows vs. avg 500.0 · {DROP:.1%} drop > 30%",
            11,
            mix(BG, RED, level),
            "mono",
        )
    elif beat == 4 and t > 0.5:
        f.text(
            QUALITY[0] + 14,
            y + 20,
            "comparing with baseline…",
            11,
            mix(BG, ACCENT, ease(span(t, 0.5, 0.7))),
            "mono",
        )

    # Run history: the baseline the anomaly check is computed from.
    node(
        f,
        HISTORY,
        "Run history",
        "last 5 healthy runs = baseline",
        "POSTGRESQL · NEON",
        style=style["history"],
    )
    base, scale, bw, gap = 330, 0.22, 30, 16
    x0 = HISTORY[0] + (HISTORY[2] - (6 * bw + 5 * gap)) / 2
    baseline_lit = final or after(beat, t, 4, 0.15)
    for i, rows in enumerate(HISTORY_ROWS):
        x = x0 + i * (bw + gap)
        f.rect(
            (x, base - rows * scale, bw, rows * scale), "#a9bbe6" if baseline_lit else BAR, radius=3
        )
        f.text(
            x + bw / 2 - f.width(f"#{37 + i}", 10, "mono") / 2,
            base + 6,
            f"#{37 + i}",
            10,
            DIM,
            "mono",
        )
    if baseline_lit:
        level = 1.0 if final or beat > 4 else ease(span(t, 0.15, 0.4))
        avg_y = base - 500 * scale
        f.line(
            [(x0 - 6, avg_y), (x0 + 6 * bw + 5 * gap + 6, avg_y)],
            mix(PANEL, ACCENT, level),
            1,
            True,
        )
        label = "avg 500.0"
        f.text(
            x0 + 6 * bw + 5 * gap + 6 - f.width(label, 11, "bold"),
            avg_y - 18,
            label,
            11,
            mix(PANEL, ACCENT, level),
            "bold",
        )
    x = x0 + 5 * (bw + gap)
    if final or after(beat, t, 1, 0.75):
        grow = 1.0 if final or beat > 5 else (ease(span(t, 0.2, 0.5)) if beat == 5 else 0.0)
        color = RED if grow > 0 else DIM
        if grow > 0:
            h = CURRENT_ROWS * scale * grow
            f.rect((x, base - h, bw, max(h, 1)), color, radius=3)
            f.text(
                x + bw / 2 - f.width(str(CURRENT_ROWS), 11, "bold") / 2,
                base - h - 18,
                str(CURRENT_ROWS),
                11,
                mix(PANEL, RED, grow),
                "bold",
            )
        else:
            f.rect((x, base - 2, bw, 2), DIM, radius=1)
        f.text(x + bw / 2 - f.width("#42", 10, "mono") / 2, base + 6, "#42", 10, color, "mono")

    # Dashboard: the latest runs with both states, then the KPI.
    node(f, DASHBOARD, "Dashboard", "runs · KPIs · filters", "WEB UI", style=style["dashboard"])
    rows = [("#40", "SUCCESS · PASS", MUTED), ("#41", "SUCCESS · PASS", MUTED)]
    if final or after(beat, t, 1, 0.75):
        failed_quality = final or after(beat, t, 5, 0.45)
        rows.append(
            (
                "#42",
                "SUCCESS · FAIL" if failed_quality else "SUCCESS · …",
                RED if failed_quality else MUTED,
            )
        )
    for i, (run, state, color) in enumerate(rows):
        f.text(DASHBOARD[0] + 14, DASHBOARD[1] + 76 + i * 20, f"{run} {state}", 11, color, "mono")
    if final or after(beat, t, 7, 0.35):
        level = 1.0 if final else ease(span(t, 0.35, 0.55))
        f.text(
            DASHBOARD[0] + 14,
            DASHBOARD[1] + 136 - 8,
            "quality incidents: 1",
            11,
            mix(PANEL, ACCENT, level),
            "bold",
        )

    # Run 0928: reported, stored, and checked.
    if beat >= 1 or final:
        pos = SLOT["quality"] if final else SLOT["api"]
        note, badge, color, note_color = f"{CURRENT_ROWS} rows", "SUCCESS", ACCENT, MUTED
        if beat == 1:
            pos = lerp(SLOT["api"], SLOT["quality"], ease(span(t, 0.72, 0.95)))
            note = "stored as #42" if t > 0.6 else note
        elif beat >= 2:
            pos, note = SLOT["quality"], "stored as #42"
        if final or after(beat, t, 5, 0.45):
            note, color, note_color = "quality FAIL", RED, RED
        card(f, pos, "run 0928", note, badge, color, note_color)
    if beat == 0:
        card(
            f,
            lerp(SLOT["pipeline"], SLOT["api"], ease(span(t, 0.1, 0.55))),
            "run 0928",
            f"{CURRENT_ROWS} rows",
            "SUCCESS",
        )
    elif beat == 1 and t < 0.72:
        pass  # drawn above, already at the API
    elif beat == 2:
        # A retry with the same data, then one with different data under the same id.
        if t < 0.5:
            go, back = ease(span(t, 0.0, 0.2)), ease(span(t, 0.38, 0.5))
            pos = lerp(lerp(SLOT["pipeline"], SLOT["api"], go), SLOT["pipeline"], back)
            ok = t > 0.25
            if back < 1:
                card(
                    f,
                    pos,
                    "run 0928",
                    "200 · stored #42" if ok else "retry, same data",
                    "RETRY",
                    GREEN if ok else ACCENT,
                    GREEN if ok else MUTED,
                )
        else:
            pos = lerp(SLOT["pipeline"], SLOT["api"], ease(span(t, 0.5, 0.68)))
            bad = t > 0.7
            card(
                f,
                pos,
                "run 0928",
                "409 · conflict" if bad else "90 rows · changed",
                "RETRY",
                RED if bad else AMBER,
                RED if bad else MUTED,
            )

    # Incident analysis: appears once requested.
    fill, border, tag_color = style["analysis"]
    f.rect(ANALYSIS, fill, border, 2 if border != LINE else 1)
    f.text(
        ANALYSIS[0] + 14, ANALYSIS[1] + 11, "INCIDENT ANALYSIS · RULE-BASED", 11, tag_color, "bold"
    )
    shown = 1.0 if final else (ease(span(t, 0.2, 0.5)) if beat == 6 else (1.0 if beat > 6 else 0.0))
    if shown > 0:
        w = f.pill(ANALYSIS[0] + 14, ANALYSIS[1] + 34, "MEDIUM", AMBER, 10, True, shown)
        f.text(
            ANALYSIS[0] + 24 + w,
            ANALYSIS[1] + 34,
            "The pipeline completed, but 1 data quality check failed: row_count_anomaly.",
            13,
            mix(BG, TEXT, shown),
        )
        f.text(
            ANALYSIS[0] + 14,
            ANALYSIS[1] + 62,
            "Far fewer rows arrived than in recent successful runs: "
            "the source may have truncated or throttled.",
            12,
            mix(BG, MUTED, shown),
        )
    else:
        f.text(ANALYSIS[0] + 14, ANALYSIS[1] + 44, "waiting for a failed check", 13, DIM)

    caption, code, explanation, _ = BEATS[beat]
    if final:
        caption = "Store every run, compare it with history, explain what failed"
        code = "Valid rows, collapsed volume"
        explanation = "Caught by the monitor, not by the pipeline"
    f.rect(DETAIL, PANEL, LINE, 1)
    f.text(DETAIL[0] + 16, DETAIL[1] + 18, code, 13, ACCENT, "mono")
    f.text(DETAIL[0] + 16, DETAIL[1] + 52, explanation, 14, MUTED)

    f.rect((30, 558, 1140, 1), LINE, radius=0)
    count = f"{beat + 1:02d} / {len(BEATS):02d}" if not final else "PipeGuard"
    f.text(30, 579, count, 13, ACCENT, "bold")
    f.text(
        105 if not final else 30 + f.width(count, 13, "bold") + 14, 575, caption, 19, TEXT, "bold"
    )
    legend = "Solid: run data   Dashed: reads and comparisons"
    f.text(1170 - f.width(legend, 11), 581, legend, 11, DIM)
    return f.image.resize(OUT, Image.LANCZOS)


def main():
    frames = []
    for beat, (*_, seconds) in enumerate(BEATS):
        count = round(seconds * FPS)
        frames += [draw_frame(beat, i / (count - 1)) for i in range(count)]
        print(f"beat {beat + 1}/{len(BEATS)}", flush=True)
    final = draw_frame(len(BEATS) - 1, 1.0, final=True)
    frames += [final] * round(HOLD_SECONDS * FPS)
    # Loop seam: fade out to the empty canvas, then fade the opening frame in.
    blank, fade = Image.new("RGB", OUT, BG), round(FADE_SECONDS * FPS)
    frames += [Image.blend(final, blank, ease((i + 1) / fade)) for i in range(fade)]
    frames[:fade] = [Image.blend(blank, frames[i], ease((i + 1) / fade)) for i in range(fade)]

    # One shared palette keeps colors stable between frames (no flicker).
    picks = frames[:: max(1, len(frames) // 16)][:16]
    sample = Image.new("RGB", (OUT[0], OUT[1] * len(picks)))
    for i, frame in enumerate(picks):
        sample.paste(frame, (0, i * OUT[1]))
    palette = sample.quantize(colors=256, method=Image.Quantize.MEDIANCUT)
    quantized = [frame.quantize(palette=palette, dither=Image.Dither.NONE) for frame in frames]
    quantized[0].save(
        ROOT / "pipeguard-flow.gif",
        save_all=True,
        append_images=quantized[1:],
        duration=round(1000 / FPS),
        loop=0,
        optimize=True,
        disposal=1,
    )
    final.save(ROOT / "pipeguard-flow.png", optimize=True)
    size = (ROOT / "pipeguard-flow.gif").stat().st_size / 1024 / 1024
    print(f"{len(frames) / FPS:.1f}s, {len(frames)} frames, {size:.2f} MiB")


if __name__ == "__main__":
    main()
