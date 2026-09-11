"""Render Fable 5.1's Agent Rotate storyboard without accounts or network access.

Run: uv run --with pillow --with imageio-ffmpeg python docs/launch/render_video.py
Use --stills-only for a quick visual review. Rendering fonts require macOS.
"""

import argparse
import math
import subprocess
from functools import lru_cache
from itertools import pairwise
from pathlib import Path

from imageio_ffmpeg import get_ffmpeg_exe
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
WIDTH, HEIGHT, FPS, DURATION = 1920, 1080, 30, 25
BG, PANEL, BORDER = "#0B1220", "#111D30", "#2B4058"
WHITE, MUTED, CYAN, LIME, RED = "#F4F7FC", "#A8B8CE", "#22D3EE", "#A3E635", "#F87171"
FONTS = {
    "regular": "/System/Library/Fonts/Supplemental/Arial.ttf",
    "bold": "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "mono": "/System/Library/Fonts/Menlo.ttc",
}
SCENES = [(0, "The quota wall"), (2.5, "Meet Agent Rotate"), (6.5, "Same-session failover"),
          (13, "Quota visibility"), (18.5, "Your controls"), (22, "Get started on GitHub")]


@lru_cache
def font(size, kind="regular"):
    return ImageFont.truetype(FONTS[kind], size)


def ease(value):
    return 1 - (1 - min(1, max(0, value))) ** 3


def mix(a, b, value):
    return a + (b - a) * value


class Canvas:
    def __init__(self):
        self.im = BACKGROUND.copy()
        self.draw = ImageDraw.Draw(self.im)

    def box(self, bounds, fill=PANEL, outline=None, radius=22, width=2):
        self.draw.rounded_rectangle(bounds, radius, fill, outline, width)

    def text(self, x, y, value, size=36, color=WHITE, kind="regular"):
        self.draw.text((x, y), value, font=font(size, kind), fill=color, anchor="lt")

    def line(self, points, color=BORDER, width=3):
        self.draw.line(points, fill=color, width=width, joint="curve")

    def chip(self, x, y, value, color=CYAN):
        w = self.draw.textlength(value, font=font(36, "mono")) + 40
        self.box((x, y, x + w, y + 62), BG, color, 12)
        self.text(x + 20, y + 13, value, 36, color, "mono")
        return w

    def wrapped(self, x, y, value, width, size=36, color=MUTED, spacing=48):
        line = ""
        for word in value.split():
            candidate = f"{line} {word}".strip()
            if self.draw.textlength(candidate, font=font(size)) > width:
                self.text(x, y, line, size, color)
                y += spacing
                line = word
            else:
                line = candidate
        self.text(x, y, line, size, color)


BACKGROUND = Image.new("RGB", (WIDTH, HEIGHT), BG)
_draw = ImageDraw.Draw(BACKGROUND)
for _y in range(HEIGHT):
    _v = 1 - abs(_y - 450) / 700
    _draw.line((0, _y, WIDTH, _y), fill=(11, round(18 + 5 * _v), round(32 + 9 * _v)))
for _x in range(96, 1840, 64):
    for _y in range(100, 1000, 64):
        _draw.ellipse((_x, _y, _x + 2, _y + 2), fill="#213047")
DASHBOARD = Image.open(ROOT.parent / "assets" / "dashboard.png").convert("RGB")


def chrome(c, t, index, label=None):
    c.text(96, 66, "AGENT ROTATE", 36, CYAN, "mono")
    if label:
        c.chip(1440, 54, label)
    else:
        c.text(1390, 66, "CLAUDE + CODEX", 36, MUTED, "mono")
    c.line((96, 1005, 1824, 1005))
    c.text(96, 1030, f"0{index + 1} / 06", 24, MUTED, "mono")
    for i, (start, _) in enumerate(SCENES):
        end = SCENES[i + 1][0] if i < 5 else DURATION
        x = 1250 + i * 98
        c.box((x, 1037, x + 78, 1042), BORDER, radius=2)
        if index == 5:
            c.box((x, 1037, x + 78, 1042), CYAN, radius=2)
            continue
        portion = min(1, max(0, (t - start) / (end - start)))
        if portion:
            c.box((x, 1037, x + 78 * portion, 1042), CYAN, radius=2)


def hook(c, t):
    c.text(96, 180, "Quota wall.", 110, WHITE, "bold")
    c.text(96, 305, "Mid-session.", 110, RED, "bold")
    c.text(100, 470, "You were in the middle of something.", 42, MUTED)
    c.box((96, 595, 1824, 929), "#09111D", BORDER)
    c.text(132, 630, "$ claude", 36, CYAN, "mono")
    c.text(132, 701, "refactoring auth module...", 44, WHITE, "mono")
    if t >= 0.6:
        c.box((126, 783, 1794, 885), "#301D2B", RED, 14)
        c.text(154, 810, "429  quota_exceeded", 52, RED, "mono")
    elif int(t * 4) % 2 == 0:
        c.box((848, 705, 872, 748), CYAN, radius=0)


def introduce(c, local):
    y = 210 + 24 * (1 - ease(local / 0.5))
    c.text(94, y, "Agent Rotate", 146, WHITE, "bold")
    c.line((100, 387, 100 + 990 * ease(local / 0.7), 387), CYAN, 8)
    c.text(100, 443, "A local router for native", 58, MUTED)
    c.text(100, 522, "Claude Code and Codex.", 70, WHITE, "bold")
    c.chip(100, 660, "RUNS ON YOUR MACHINE")
    c.chip(100, 746, "YOUR OWN ACCOUNTS", LIME)
    c.text(100, 890, "v0.2.0", 36, MUTED, "mono")
    # A simple route mark, drawn from primitives rather than a third-party logo.
    c.line([(1455, 342), (1550, 342), (1550, 678), (1680, 678)], CYAN, 8)
    c.line([(1550, 342), (1680, 342)], BORDER, 8)
    for x, yy, col in [(1440, 342, CYAN), (1680, 342, MUTED), (1680, 678, LIME)]:
        c.draw.ellipse((x - 30, yy - 30, x + 30, yy + 30), fill=BG, outline=col, width=7)


def node(c, bounds, title, subtitle, color=CYAN):
    x, y, _, _ = bounds
    c.box(bounds, PANEL, color, 20, 3)
    c.text(x + 28, y + 28, title, 40, WHITE, "bold")
    c.text(x + 28, y + 91, subtitle, 36, color)


def request(c, point, color=CYAN):
    x, y = point
    c.box((x - 83, y - 28, x + 83, y + 28), BG, color, 28, 3)
    c.text(x - 64, y - 17, "request", 30, color, "mono")


def travel(c, points, progress, color=CYAN):
    lengths = [math.dist(a, b) for a, b in pairwise(points)]
    remaining = sum(lengths) * min(1, max(0, progress))
    for (a, b), length in zip(pairwise(points), lengths, strict=True):
        if remaining <= length:
            request(c, (mix(a[0], b[0], remaining / length),
                        mix(a[1], b[1], remaining / length)), color)
            return
        remaining -= length


def failover(c, local):
    c.text(96, 171, "Failover before a response", 76, WHITE, "bold")
    c.text(96, 265, "is delivered.", 76, WHITE, "bold")
    c.text(100, 372, "Same provider. Same model. Same session. No partial replay.", 40, MUTED)
    c.line((516, 589, 752, 589), CYAN, 5)
    c.line([(1154, 589), (1250, 589), (1250, 495), (1390, 495)],
           RED if local >= 2.7 else BORDER, 5)
    c.line([(1250, 589), (1250, 714), (1390, 714)],
           LIME if local >= 4.4 else BORDER, 5)
    node(c, (96, 508, 516, 673), "Claude Code", "session stays open")
    node(c, (752, 508, 1154, 673), "Agent Rotate", "local request router")
    node(c, (1390, 412, 1824, 577), "Account A", "429 · cooldown" if local >= 2.7
         else "first attempt", RED if local >= 2.7 else MUTED)
    node(c, (1390, 632, 1824, 797), "Account B", "OK · same provider" if local >= 4.4
         else "same provider", LIME if local >= 4.4 else MUTED)
    upper = [(1154, 589), (1250, 589), (1250, 495), (1390, 495)]
    lower = [(1154, 589), (1250, 589), (1250, 714), (1390, 714)]
    if 1.3 <= local < 2.0:
        travel(c, [(516, 589), (752, 589)], (local - 1.3) / 0.7)
    elif 2.0 <= local < 2.7:
        travel(c, upper, (local - 2.0) / 0.7)
    elif 3.0 <= local < 3.5:
        travel(c, list(reversed(upper)), (local - 3.0) / 0.5, RED)
    elif 3.5 <= local < 4.4:
        travel(c, lower, (local - 3.5) / 0.9)
    # Hold the full scope for the whole scene, so viewers have time to read it.
    c.wrapped(100, 838,
              "Scope: the quota-rejected request is retried on another eligible account of the "
              "same provider before any response is delivered.", 1710, 36)


def visibility(c, local):
    c.text(96, 166, "See every account's quota", 78, WHITE, "bold")
    c.text(96, 261, "at a glance.", 78, WHITE, "bold")
    # Actual dashboard renderer export. The image itself contains only sample metadata.
    # Show the complete quota table; omit the separate routed-session table.
    panel = DASHBOARD.crop((0, 0, 1463, 403)).resize((1728, 476), Image.Resampling.LANCZOS)
    c.im.paste(panel, (96 + round(50 * (1 - ease(local / 0.6))), 381))
    labels = [("CREDENTIAL HEALTH", 100, 618), ("QUOTA WINDOWS", 760, 876),
              ("RESET TIMERS", 1400, 1490)]
    for i, (label, x, target) in enumerate(labels):
        if local >= 0.7 + i * 0.65:
            width = c.chip(x, 899, label)
            c.line([(x + width / 2, 898), (x + width / 2, 879), (target, 866),
                    (target, 852)], CYAN, 3)


def control(c, local):
    c.text(96, 176, "You stay in control.", 96, WHITE, "bold")
    c.text(100, 311, "Separate provider pools. Sticky by default.", 44, MUTED)
    c.text(100, 374, "Native approvals and sandbox unchanged.", 44, MUTED)
    labels = ["Project-to-pool mappings", "Optional proactive thresholds",
              "Saved session resume", "Read-only MCP tools"]
    for i, label in enumerate(labels):
        delay = i * 0.08
        if local < delay:
            continue
        x, y = 100 + (i % 2) * 880, 510 + (i // 2) * 172
        y += round(18 * (1 - ease((local - delay) / 0.4)))
        c.box((x, y, x + 838, y + 137), PANEL, BORDER, 18)
        c.line((x + 2, y + 22, x + 2, y + 115), CYAN, 5)
        c.text(x + 32, y + 46, label, 43, WHITE, "bold")
    c.text(100, 899, "Routing applies to wrapper-launched sessions.", 38, MUTED)


def cta(c, local):
    c.text(96, 189, "Agent Rotate 0.2.0", 112, WHITE, "bold")
    c.text(100, 343, "Local quota failover for", 66, WHITE, "bold")
    c.text(100, 426, "native Claude Code and Codex", 66, WHITE, "bold")
    c.text(100, 563, "GET STARTED ON GITHUB", 36, LIME, "mono")
    c.box((100, 629, 1824, 751), BG, LIME, 22, 4)
    c.text(144, 665, "github.com/davefmurray/agent-rotate", 48, LIME, "mono")
    c.wrapped(100, 826,
              "Sample dashboard data shown. Tested with injected 429s and real fallback inference; "
              "natural quota exhaustion not yet verified.", 1710, 36)


def frame(t):
    c = Canvas()
    index = max(i for i, (start, _) in enumerate(SCENES) if start <= t)
    label = "ILLUSTRATION" if index in (0, 1, 2) else "SAMPLE DATA" if index == 3 else None
    chrome(c, t, index, label)
    [hook, introduce, failover, visibility, control, cta][index](c, t - SCENES[index][0])
    return c.im


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stills-only", action="store_true")
    args = parser.parse_args()
    times = [1.5, 5.2, 11.8, 17.5, 21.2, 24.5]
    contact = Image.new("RGB", (1920, 1740), BG)
    d = ImageDraw.Draw(contact)
    for i, t in enumerate(times):
        im = frame(t)
        im.save(ROOT / f"scene-{i + 1}.png")
        x, y = (i % 2) * 960, (i // 2) * 580
        contact.paste(im.resize((960, 540), Image.Resampling.LANCZOS), (x, y + 40))
        d.text((x + 48, y + 8), f"{t:04.1f}s · {SCENES[i][1]}",
               font=font(25, "mono"), fill=MUTED)
    contact.save(ROOT / "contact-sheet.png")
    frame(1.0).save(ROOT / "poster.png")
    frame(24.5).save(ROOT / "end-card.png")
    if args.stills_only:
        print("Rendered stills and contact sheet.")
        return
    command = [get_ffmpeg_exe(), "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
               "-s", f"{WIDTH}x{HEIGHT}", "-r", str(FPS), "-i", "-", "-an", "-c:v", "libx264",
               "-preset", "fast", "-crf", "19", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
               str(ROOT / "agent-rotate-promo.mp4")]
    process = subprocess.Popen(command, stdin=subprocess.PIPE)
    try:
        for i in range(FPS * DURATION):
            process.stdin.write(frame(i / FPS).tobytes())
            if i % 150 == 0:
                print(f"Rendered {i // FPS}s / {DURATION}s", flush=True)
    finally:
        process.stdin.close()
    if process.wait() != 0:
        raise RuntimeError("Video encoder failed")
    print("Rendered 25-second H.264 MP4.")


if __name__ == "__main__":
    main()
