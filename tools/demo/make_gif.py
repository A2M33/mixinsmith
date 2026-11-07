"""Render assets/demo.gif from real captured outputs (captures/*.txt), in the A2M33 palette.

The captures come from a Fabric 1.21.1 (Yarn) test mod with a mixin aimed at the Mojang name `hurt`.
Windows only as written (Consolas from C:/Windows/Fonts).

    pip install pillow
    python tools/demo/make_gif.py
"""
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
CAPTURES = HERE / "captures"
OUT = HERE.parent.parent / "assets" / "demo.gif"

MONO = ImageFont.truetype("C:/Windows/Fonts/consola.ttf", 15)
MONO_BOLD = ImageFont.truetype("C:/Windows/Fonts/consolab.ttf", 15)
LABEL = ImageFont.truetype(str(HERE.parent / "banner" / "fonts" / "Barlow-Medium.woff2"), 16)

# Light values from tokens.css
CAB = (0xE3, 0xE5, 0xE0)
PANEL = (0xF4, 0xF5, 0xF2)
INSET = (0xD5, 0xD9, 0xD3)
LINE = (0xB9, 0xBF, 0xB7)
INK = (0x1D, 0x24, 0x20)
INK_2 = (0x56, 0x60, 0x5A)
AMBER = (0xD9, 0x92, 0x11)
AMBER_INK = (0x6B, 0x46, 0x00)
FAULT = (0xB8, 0x32, 0x2A)
OK = (0x3D, 0x7A, 0x4F)

W, COLS, LH = 980, 104, 21
ROWS = 22
MARGIN, PAD, BAR = 12, 22, 40
H = MARGIN * 2 + BAR + PAD + ROWS * LH + PAD // 2

# Line kinds: (colour, bold, amber marker)
CMD, NOTE, TEXT, DIM, KEY, BAD, GOOD = "cmd", "note", "text", "dim", "key", "bad", "good"
STYLE = {
    CMD: (INK, True, False),
    NOTE: (INK_2, False, False),
    TEXT: (INK, False, False),
    DIM: (INK_2, False, False),
    KEY: (AMBER_INK, False, True),
    BAD: (FAULT, False, False),
    GOOD: (OK, False, False),
}


def kind(line):
    s = line.strip()
    if line.startswith("$"):
        return CMD
    if line.startswith("#"):
        return NOTE
    if s.startswith(("COMPILE OK", "SERVER OK")):
        return GOOD
    if s.startswith(("FAILED", "MIXIN", "mcsrc:")):
        return BAD
    if s.startswith(("In yarn", "mixin target")):
        return KEY
    if s.startswith(("->", "full:")):
        return DIM
    return TEXT


def lines(name, keep=None):
    t = (CAPTURES / name).read_text(encoding="utf-8").strip().splitlines()
    return t[:keep] if keep else t


SCRIPT = [
    ("# a mixin into LivingEntity#hurt (the Mojang name) in a Yarn project", None),
    ("$ python mcbuild.py compile", lines("1-compile.txt")),
    ("$ python mcbuild.py server", lines("2-server.txt", 4)),
    ("$ python mcsrc.py method LivingEntity#hurt", lines("3-lookup.txt")),
    ("$ python mcsrc.py method Entity#damage", lines("4-damage.txt")),
    ('# fix: @Inject(method = "damage(Lnet/minecraft/entity/damage/DamageSource;F)Z")', None),
    ("$ python mcbuild.py server", lines("5-server.txt")),
]

frames, durations = [], []
screen: list[tuple[str, str]] = []
lamp = INSET  # status lamp in the title bar: grey idle, amber running, red fault, green ok


def lamp_image(colour, size=12, scale=8):
    """An anti-aliased round lamp (drawn large, scaled down)."""
    big = Image.new("RGBA", (size * scale, size * scale), (0, 0, 0, 0))
    edge = LINE if colour == INSET else colour
    ImageDraw.Draw(big).ellipse((0, 0, size * scale - 1, size * scale - 1), fill=colour, outline=edge, width=scale)
    return big.resize((size, size), Image.LANCZOS)


def render():
    img = Image.new("RGB", (W, H), CAB)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((MARGIN, MARGIN, W - MARGIN - 1, H - MARGIN - 1), radius=6, fill=PANEL, outline=LINE)
    y_mid = MARGIN + BAR // 2
    x = MARGIN + PAD
    img.paste(lamp_image(lamp), (x, y_mid - 6), lamp_image(lamp))
    d.text((x + 22, y_mid), "mixinsmith", font=LABEL, fill=INK_2, anchor="lm")
    d.line((MARGIN + 1, MARGIN + BAR, W - MARGIN - 2, MARGIN + BAR), fill=LINE)
    top = MARGIN + BAR + PAD // 2 + 4
    for r, (text, k) in enumerate(screen[-ROWS:]):
        colour, bold, marker = STYLE[k]
        y = top + r * LH
        if marker:
            d.rectangle((x - 12, y + 1, x - 9, y + LH - 3), fill=AMBER)
        d.text((x, y), text, font=MONO_BOLD if bold else MONO, fill=colour)
    return img


def push(text, k):
    for part in textwrap.wrap(text, COLS, subsequent_indent="    ") or [""]:
        screen.append((part, k))


def snap(ms):
    frames.append(render())
    durations.append(ms)


snap(600)
for cmd, out in SCRIPT:
    if cmd.startswith("$"):
        lamp = AMBER
        screen.append(("$ ", CMD))
        for k in range(2, len(cmd) + 1, 3):
            screen[-1] = (cmd[:k], CMD)
            snap(35)
        screen[-1] = (cmd, CMD)
        snap(500)
    else:
        push(cmd, NOTE)
        snap(1400)
    kinds = [kind(line) for line in out or []]
    for line, k in zip(out or [], kinds):
        push(line, k)
        snap(220)
    if out:
        lamp = FAULT if BAD in kinds else OK if GOOD in kinds else INSET
        snap(1600)
    screen.append(("", TEXT))
snap(3500)

# One shared palette for every frame, no dithering: the exact token colours first, then the
# anti-aliasing shades median-cut from frames that show each lamp state.
sample = [frames[i] for i in sorted({0, len(frames) // 3, len(frames) // 2, len(frames) - 1})]
sheet = Image.new("RGB", (W, H * len(sample)))
for i, f in enumerate(sample):
    sheet.paste(f, (0, H * i))
TOKENS = [CAB, PANEL, INSET, LINE, INK, INK_2, AMBER, AMBER_INK, FAULT, OK]
shades = sheet.quantize(colors=256 - len(TOKENS), method=Image.MEDIANCUT).getpalette()[: 3 * (256 - len(TOKENS))]
palette = Image.new("P", (1, 1))
palette.putpalette([c for rgb in TOKENS for c in rgb] + shades)
pal = [f.quantize(palette=palette, dither=Image.NONE) for f in frames]
pal[0].save(OUT, save_all=True, append_images=pal[1:], duration=durations, loop=0, optimize=True)
print(OUT, len(frames), "frames", OUT.stat().st_size // 1024, "KB")
