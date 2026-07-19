"""Art-directed product covers — four distinct visual languages so products
look individually designed rather than template-swapped:

  editorial — split layout, serif headline, hairline rules (civic/news niches)
  stat      — dark field, giant backdrop numeral, bold sans (sports/trading)
  banner    — centered classic label, double rules, scattered dots (seasonal/warm)
  siderail  — white page, dot-grid paper texture, accent rail (student/planner)

The spec's theme may set "style" and "font" explicitly (the generator's LLM is
prompted to art-direct per niche); otherwise both are picked deterministically
from the product name so a catalog never looks uniform.
"""

from __future__ import annotations

import hashlib
import logging
import re

from PIL import Image, ImageDraw, ImageFont

log = logging.getLogger("cover")

WIDTH, HEIGHT = 1280, 720
STYLES = ("editorial", "stat", "banner", "siderail")

FONT_FILES = {
    ("serif", "bold"): ["/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
                        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"],
    ("serif", "regular"): ["/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
                           "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"],
    ("serif", "italic"): ["/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf",
                          "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"],
    ("sans", "bold"): ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                       "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"],
    ("sans", "regular"): ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
    ("sans", "italic"): ["/usr/share/fonts/truetype/liberation/LiberationSans-Italic.ttf",
                         "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
    ("mono", "bold"): ["/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"],
    ("mono", "regular"): ["/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"],
}


def _rgb(color: str) -> tuple[int, int, int]:
    c = str(color or "1F4E5F").lstrip("#")[:6].ljust(6, "0")
    return tuple(int(c[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _mix(a: tuple, b: tuple, t: float) -> tuple[int, int, int]:
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))  # type: ignore[return-value]


def _font(family: str, weight: str, size: int):
    for path in FONT_FILES.get((family, weight), []) + FONT_FILES[("sans", "bold")]:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _wrap(draw, text: str, font, max_width: int, max_lines: int = 3) -> list[str]:
    words, lines, current = str(text).split(), [], ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines[:max_lines]


def _pick(product_name: str, options: tuple, salt: str) -> str:
    digest = hashlib.md5(f"{salt}:{product_name}".encode()).digest()
    return options[digest[0] % len(options)]


def _spaced(text: str) -> str:
    return " ".join(text.upper())


# --- texture helpers ---------------------------------------------------------

def _dot_grid(draw, color, spacing=34, r=2, box=(0, 0, WIDTH, HEIGHT)):
    for x in range(box[0] + spacing // 2, box[2], spacing):
        for y in range(box[1] + spacing // 2, box[3], spacing):
            draw.ellipse([x - r, y - r, x + r, y + r], fill=color)


def _diag_stripes(draw, color, box, gap=48, width=3):
    x0, y0, x1, y1 = box
    for offset in range(-(y1 - y0), x1 - x0, gap):
        draw.line([(x0 + offset, y1), (x0 + offset + (y1 - y0), y0)], fill=color, width=width)


def _scatter(draw, colors, box, n=26, seed_text="snow"):
    seed = int(hashlib.md5(seed_text.encode()).hexdigest(), 16)
    x0, y0, x1, y1 = box
    for i in range(n):
        h = hashlib.md5(f"{seed}:{i}".encode()).digest()
        x = x0 + h[0] * (x1 - x0) // 255
        y = y0 + h[1] * (y1 - y0) // 255
        r = 2 + h[2] % 4
        draw.ellipse([x - r, y - r, x + r, y + r], fill=colors[i % len(colors)])


# --- mini table (shared ingredient, styled per call) -------------------------

def _mini_table(draw, sheet, origin, cell_w, cell_h, header_fill, header_text,
                row_a, row_b, body_text, font_family, n_cols=4, n_rows=4, outline=None):
    columns = (sheet.get("columns") or [{"header": "Item"}])[:n_cols]
    rows_data = sheet.get("rows") or []
    hf, cf = _font(font_family, "bold", 21), _font("sans", "regular", 19)
    ox, oy = origin
    for i, col in enumerate(columns):
        x0 = ox + i * cell_w
        draw.rectangle([x0, oy, x0 + cell_w - 3, oy + cell_h], fill=header_fill)
        draw.text((x0 + 12, oy + 11), str(col.get("header", ""))[:13], font=hf, fill=header_text)
    for r in range(n_rows):
        y0 = oy + cell_h + r * cell_h
        row = rows_data[r] if r < len(rows_data) and isinstance(rows_data[r], list) else []
        for i in range(len(columns)):
            x0 = ox + i * cell_w
            fill = row_a if r % 2 == 0 else row_b
            draw.rectangle([x0, y0, x0 + cell_w - 3, y0 + cell_h], fill=fill, outline=outline)
            value = row[i] if i < len(row) else ""
            text = "ƒx" if isinstance(value, str) and value.startswith("=") else str(value if value is not None else "")[:14]
            draw.text((x0 + 12, y0 + 11), text, font=cf, fill=body_text)


# --- the four styles ---------------------------------------------------------

def _style_editorial(img, draw, spec, theme, font_family):
    primary, secondary, accent = theme
    panel_w = 560
    draw.rectangle([0, 0, WIDTH, HEIGHT], fill=secondary)
    draw.rectangle([0, 0, panel_w, HEIGHT], fill=primary)
    rule = _mix(primary, (255, 255, 255), 0.12)
    for y in range(90, HEIGHT, 44):
        draw.line([(36, y), (panel_w - 36, y)], fill=rule, width=1)

    hfont = _font(font_family, "bold", 58)
    y = 74
    for line in _wrap(draw, spec.get("product_name", ""), hfont, panel_w - 100):
        draw.rectangle([36, y, 36 + draw.textlength(line, font=hfont) + 16, y + 66], fill=primary)
        draw.text((44, y), line, font=hfont, fill=(255, 255, 255))
        y += 70
    draw.rectangle([44, y + 8, 168, y + 15], fill=_rgb_t(accent))
    tfont = _font(font_family, "italic", 26)
    y += 40
    for line in _wrap(draw, spec.get("tagline", ""), tfont, panel_w - 100, 2):
        draw.text((44, y), line, font=tfont, fill=_mix(primary, (255, 255, 255), 0.75))
        y += 34
    draw.text((44, HEIGHT - 56), _spaced("Excel · Google Sheets · Instant"),
              font=_font("mono", "regular", 16), fill=_mix(primary, (255, 255, 255), 0.55))

    sheets = spec.get("sheets") or [{}]
    _mini_table(draw, sheets[0], (panel_w + 56, 200), 158, 54,
                header_fill=_rgb_t(accent), header_text=(255, 255, 255),
                row_a=(255, 255, 255), row_b=_mix(secondary, (255, 255, 255), 0.5),
                body_text=(70, 70, 70), font_family=font_family, outline=(215, 210, 200))


def _style_stat(img, draw, spec, theme, font_family):
    primary, secondary, accent = theme
    draw.rectangle([0, 0, WIDTH, HEIGHT], fill=primary)
    _diag_stripes(draw, _mix(primary, (255, 255, 255), 0.05), (0, HEIGHT // 2, WIDTH, HEIGHT))
    match = re.search(r"(20\d\d)", str(spec.get("product_name", "")))
    numeral = match.group(1)[-2:] if match else str(spec.get("product_name", "X"))[:1].upper()
    nfont = _font(font_family, "bold", 430)
    nw = draw.textlength(numeral, font=nfont)
    draw.text((WIDTH - nw - 40, HEIGHT - 500), numeral, font=nfont,
              fill=_mix(primary, (255, 255, 255), 0.08))

    hfont = _font(font_family, "bold", 62)
    y = 78
    for line in _wrap(draw, spec.get("product_name", ""), hfont, 760):
        draw.text((56, y), line, font=hfont, fill=(255, 255, 255))
        y += 72
    draw.rectangle([56, y + 6, 300, y + 16], fill=_rgb_t(accent))
    y += 44
    for line in _wrap(draw, spec.get("tagline", ""), _font("sans", "regular", 26), 700, 2):
        draw.text((58, y), line, font=_font("sans", "regular", 26),
                  fill=_mix(primary, (255, 255, 255), 0.7))
        y += 34

    sheets = spec.get("sheets") or [{}]
    _mini_table(draw, sheets[0], (56, HEIGHT - 250), 168, 52,
                header_fill=_rgb_t(accent), header_text=primary,
                row_a=_mix(primary, (255, 255, 255), 0.09),
                row_b=_mix(primary, (255, 255, 255), 0.05),
                body_text=_mix(primary, (255, 255, 255), 0.85), font_family=font_family)
    badge = _spaced("Excel + Sheets")
    bfont = _font("mono", "bold", 17)
    bw = draw.textlength(badge, font=bfont)
    draw.rounded_rectangle([WIDTH - bw - 100, HEIGHT - 74, WIDTH - 48, HEIGHT - 34],
                           radius=6, outline=_rgb_t(accent), width=2)
    draw.text((WIDTH - bw - 74, HEIGHT - 64), badge, font=bfont, fill=_rgb_t(accent))


def _style_banner(img, draw, spec, theme, font_family):
    primary, secondary, accent = theme
    draw.rectangle([0, 0, WIDTH, HEIGHT], fill=secondary)
    _scatter(draw, [_rgb_t(accent), _mix(primary, secondary, 0.5)], (0, 0, WIDTH, 150),
             seed_text=spec.get("product_name", ""))
    _scatter(draw, [_mix(primary, secondary, 0.6), _rgb_t(accent)], (0, HEIGHT - 130, WIDTH, HEIGHT),
             seed_text=spec.get("tagline", "x"))
    for dy in (64, 72):
        draw.line([(WIDTH // 2 - 320, dy), (WIDTH // 2 + 320, dy)], fill=primary, width=2)

    hfont = _font(font_family, "bold", 56)
    y = 108
    for line in _wrap(draw, spec.get("product_name", ""), hfont, 900):
        lw = draw.textlength(line, font=hfont)
        draw.text(((WIDTH - lw) / 2, y), line, font=hfont, fill=primary)
        y += 66
    ribbon = _spaced(str(spec.get("tagline", ""))[:52])
    rfont = _font("mono", "bold", 17)
    rw = draw.textlength(ribbon, font=rfont)
    draw.rectangle([(WIDTH - rw) / 2 - 24, y + 10, (WIDTH + rw) / 2 + 24, y + 48], fill=_rgb_t(accent))
    draw.text(((WIDTH - rw) / 2, y + 20), ribbon, font=rfont, fill=(255, 255, 255))

    sheets = spec.get("sheets") or [{}]
    table_w = 4 * 168
    _mini_table(draw, sheets[0], ((WIDTH - table_w) // 2, y + 96), 168, 52,
                header_fill=primary, header_text=(255, 255, 255),
                row_a=(255, 255, 255), row_b=_mix(secondary, (255, 255, 255), 0.55),
                body_text=(80, 70, 60), font_family=font_family, outline=_mix(primary, secondary, 0.75))
    for dy in (HEIGHT - 46, HEIGHT - 38):
        draw.line([(WIDTH // 2 - 320, dy), (WIDTH // 2 + 320, dy)], fill=primary, width=2)


def _style_siderail(img, draw, spec, theme, font_family):
    primary, secondary, accent = theme
    draw.rectangle([0, 0, WIDTH, HEIGHT], fill=(252, 252, 250))
    _dot_grid(draw, (225, 225, 222))
    draw.rectangle([0, 0, 116, HEIGHT], fill=primary)
    for i, y in enumerate(range(56, 260, 64)):
        fill = _rgb_t(accent) if i == 0 else _mix(primary, (255, 255, 255), 0.25)
        draw.rectangle([40, y, 76, y + 36], fill=fill)

    hfont = _font(font_family, "bold", 58)
    y = 84
    for line in _wrap(draw, spec.get("product_name", ""), hfont, 880):
        draw.text((170, y), line, font=hfont, fill=primary)
        y += 68
    for line in _wrap(draw, spec.get("tagline", ""), _font(font_family, "italic", 26), 760, 2):
        draw.text((172, y + 8), line, font=_font(font_family, "italic", 26), fill=(120, 120, 118))
        y += 36

    # sticky note, slightly rotated — the human touch
    note = Image.new("RGBA", (190, 90), (0, 0, 0, 0))
    nd = ImageDraw.Draw(note)
    nd.rectangle([0, 0, 189, 89], fill=_rgb_t(accent))
    match = re.search(r"(20\d\d(?:-\d\d)?)", str(spec.get("product_name", "")))
    nd.text((16, 18), match.group(1) if match else "NEW", font=_font("mono", "bold", 30), fill=(255, 255, 255))
    nd.text((16, 56), _spaced("edition"), font=_font("mono", "regular", 14), fill=_mix(_rgb_t(accent), (255, 255, 255), 0.75))
    note = note.rotate(-4, expand=True)
    img.paste(note, (WIDTH - 260, 64), note)

    sheets = spec.get("sheets") or [{}]
    _mini_table(draw, sheets[0], (170, y + 42), 170, 54,
                header_fill=primary, header_text=(255, 255, 255),
                row_a=(255, 255, 255), row_b=secondary,
                body_text=(75, 75, 75), font_family=font_family, outline=(220, 220, 218))
    draw.text((170, HEIGHT - 52), _spaced("Works in Excel and Google Sheets"),
              font=_font("mono", "regular", 15), fill=(150, 150, 148))


_rgb_t = _rgb  # readability alias: theme entries already parsed where tuples are passed


STYLE_FNS = {"editorial": _style_editorial, "stat": _style_stat,
             "banner": _style_banner, "siderail": _style_siderail}


def _resolve(spec: dict) -> tuple[tuple, tuple, tuple, str, str]:
    t = spec.get("theme") or {}
    primary, secondary = _rgb(t.get("primary", "1F4E5F")), _rgb(t.get("secondary", "EAF2F4"))
    accent = t.get("accent", "F4A259")
    name = str(spec.get("product_name", ""))
    style = t.get("style") if t.get("style") in STYLES else _pick(name, STYLES, "style")
    font = t.get("font") if t.get("font") in ("serif", "sans", "mono") else _pick(name, ("serif", "sans"), "font")
    return primary, secondary, accent, style, font


def render_cover(spec: dict, out_path: str) -> str:
    primary, secondary, accent, style, font = _resolve(spec)
    img = Image.new("RGB", (WIDTH, HEIGHT), secondary)
    draw = ImageDraw.Draw(img)
    STYLE_FNS[style](img, draw, spec, (primary, secondary, accent), font)
    img.save(out_path, "PNG")
    return out_path


def render_sheet_preview(sheet_spec: dict, spec: dict, out_path: str) -> str:
    """Per-sheet gallery image, inheriting the product's art direction."""
    primary, secondary, accent, style, font = _resolve(spec)
    img = Image.new("RGB", (WIDTH, HEIGHT), (251, 251, 249))
    draw = ImageDraw.Draw(img)
    if style == "siderail":
        _dot_grid(draw, (228, 228, 225))
    draw.rectangle([0, 0, WIDTH, 70], fill=primary)
    draw.rectangle([0, 70, WIDTH, 76], fill=_rgb(accent))
    draw.text((44, 14), str(sheet_spec.get("name", "Sheet"))[:60],
              font=_font(font, "bold", 34), fill=(255, 255, 255))
    if sheet_spec.get("description"):
        draw.text((44, 92), str(sheet_spec["description"])[:110],
                  font=_font(font, "italic", 22), fill=(105, 105, 102))

    columns = (sheet_spec.get("columns") or [{"header": "Item"}])[:5]
    cell_w = min(280, (WIDTH - 80) // len(columns))
    _mini_table(draw, sheet_spec, (40, 148), cell_w, 56,
                header_fill=primary, header_text=(255, 255, 255),
                row_a=(255, 255, 255), row_b=secondary,
                body_text=(72, 72, 72), font_family=font, n_cols=5, n_rows=8,
                outline=(222, 222, 219))
    draw.text((40, HEIGHT - 46), _spaced("Excel · Google Sheets"),
              font=_font("mono", "regular", 15), fill=(160, 160, 157))
    img.save(out_path, "PNG")
    return out_path


def render_gallery(spec: dict, base_path: str, max_sheets: int = 3) -> list[str]:
    """Cover + one preview per data sheet (capped). base_path ends with .png."""
    paths = [render_cover(spec, base_path)]
    for i, sheet in enumerate((spec.get("sheets") or [])[:max_sheets]):
        out = base_path.replace(".png", f"-sheet{i + 1}.png")
        try:
            paths.append(render_sheet_preview(sheet, spec, out))
        except Exception as exc:  # noqa: BLE001 — gallery is additive, never blocking
            log.warning("sheet preview %d failed: %s", i + 1, exc)
    return paths
