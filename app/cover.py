"""Product cover image (PNG) rendered from the spec's theme — listings with a
visual convert far better than bare files. Pure Pillow, no external assets:
a themed title block, a miniature preview table built from the first sheet's
real headers, and an "Excel & Google Sheets" badge.
"""

from __future__ import annotations

import logging

from PIL import Image, ImageDraw, ImageFont

log = logging.getLogger("cover")

WIDTH, HEIGHT = 1280, 720
FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]


def _rgb(color: str) -> tuple[int, int, int]:
    c = str(color or "1F4E5F").lstrip("#")[:6].ljust(6, "0")
    return tuple(int(c[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    words, lines, current = text.split(), [], ""
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
    return lines[:3]


def render_cover(spec: dict, out_path: str) -> str:
    theme = spec.get("theme") or {}
    primary = _rgb(theme.get("primary", "1F4E5F"))
    secondary = _rgb(theme.get("secondary", "EAF2F4"))
    accent = _rgb(theme.get("accent", "F4A259"))

    img = Image.new("RGB", (WIDTH, HEIGHT), secondary)
    draw = ImageDraw.Draw(img)

    # Left accent stripe + title block
    draw.rectangle([0, 0, 18, HEIGHT], fill=accent)
    title_font, tagline_font = _font(56), _font(26)
    title_lines = _wrap(draw, str(spec.get("product_name") or "Spreadsheet Template"),
                        title_font, WIDTH - 140)
    y = 70
    for line in title_lines:
        draw.text((70, y), line, font=title_font, fill=primary)
        y += 68
    tagline = str(spec.get("tagline") or "")[:110]
    if tagline:
        draw.text((70, y + 6), tagline, font=tagline_font, fill=(90, 90, 90))
        y += 46

    # Miniature preview table from the first sheet's real headers
    sheets = spec.get("sheets") or []
    columns = (sheets[0].get("columns") if sheets else None) or []
    headers = [str(c.get("header", ""))[:14] for c in columns[:4]] or ["Item", "Amount"]
    rows_data = (sheets[0].get("rows") if sheets else None) or []

    table_top = max(y + 40, 300)
    table_left, cell_h = 70, 52
    cell_w = min(270, (WIDTH - 2 * table_left) // len(headers))
    header_font, cell_font = _font(24), _font(22)

    for i, header in enumerate(headers):
        x0 = table_left + i * cell_w
        draw.rectangle([x0, table_top, x0 + cell_w - 4, table_top + cell_h], fill=primary)
        draw.text((x0 + 14, table_top + 13), header, font=header_font, fill=(255, 255, 255))
    for r in range(4):
        y0 = table_top + cell_h + r * cell_h
        row = rows_data[r] if r < len(rows_data) and isinstance(rows_data[r], list) else []
        for i in range(len(headers)):
            x0 = table_left + i * cell_w
            fill = (255, 255, 255) if r % 2 == 0 else secondary
            draw.rectangle([x0, y0, x0 + cell_w - 4, y0 + cell_h], fill=fill,
                           outline=(215, 215, 215))
            value = row[i] if i < len(row) else ""
            text = "ƒx" if isinstance(value, str) and value.startswith("=") else str(value)[:16]
            draw.text((x0 + 14, y0 + 13), text, font=cell_font, fill=(70, 70, 70))

    # Badge
    badge_font = _font(24)
    badge_text = "Excel & Google Sheets  •  Instant Download"
    tw = draw.textlength(badge_text, font=badge_font)
    bx, by = WIDTH - tw - 90, HEIGHT - 78
    draw.rounded_rectangle([bx - 22, by - 14, bx + tw + 22, by + 40], radius=22, fill=accent)
    draw.text((bx, by), badge_text, font=badge_font, fill=(255, 255, 255))

    img.save(out_path, "PNG")
    return out_path


def render_sheet_preview(sheet_spec: dict, theme: dict, out_path: str) -> str:
    """A dedicated preview image for ONE sheet — top listings show every tab,
    so each data sheet gets its own gallery image."""
    primary = _rgb((theme or {}).get("primary", "1F4E5F"))
    secondary = _rgb((theme or {}).get("secondary", "EAF2F4"))
    accent = _rgb((theme or {}).get("accent", "F4A259"))

    img = Image.new("RGB", (WIDTH, HEIGHT), (250, 250, 250))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, WIDTH, 64], fill=primary)
    draw.rectangle([0, 64, WIDTH, 70], fill=accent)
    draw.text((40, 14), str(sheet_spec.get("name", "Sheet"))[:60], font=_font(34),
              fill=(255, 255, 255))
    if sheet_spec.get("description"):
        draw.text((40, 86), str(sheet_spec["description"])[:110], font=_font(22),
                  fill=(90, 90, 90))

    columns = sheet_spec.get("columns") or []
    headers = [str(c.get("header", ""))[:16] for c in columns[:5]] or ["Item"]
    rows_data = sheet_spec.get("rows") or []
    table_top, table_left, cell_h = 140, 40, 56
    cell_w = min(280, (WIDTH - 2 * table_left) // len(headers))
    header_font, cell_font = _font(24), _font(22)

    for i, header in enumerate(headers):
        x0 = table_left + i * cell_w
        draw.rectangle([x0, table_top, x0 + cell_w - 4, table_top + cell_h], fill=primary)
        draw.text((x0 + 14, table_top + 15), header, font=header_font, fill=(255, 255, 255))
    for r in range(min(8, max(4, len(rows_data)))):
        y0 = table_top + cell_h + r * cell_h
        row = rows_data[r] if r < len(rows_data) and isinstance(rows_data[r], list) else []
        for i in range(len(headers)):
            x0 = table_left + i * cell_w
            draw.rectangle([x0, y0, x0 + cell_w - 4, y0 + cell_h],
                           fill=(255, 255, 255) if r % 2 == 0 else secondary,
                           outline=(220, 220, 220))
            value = row[i] if i < len(row) else ""
            text = "ƒx auto" if isinstance(value, str) and value.startswith("=") else str(value)[:18]
            draw.text((x0 + 14, y0 + 15), text, font=cell_font, fill=(70, 70, 70))

    img.save(out_path, "PNG")
    return out_path


def render_gallery(spec: dict, base_path: str, max_sheets: int = 3) -> list[str]:
    """Cover + one preview per data sheet (capped). base_path ends with .png."""
    paths = [render_cover(spec, base_path)]
    theme = spec.get("theme") or {}
    for i, sheet in enumerate((spec.get("sheets") or [])[:max_sheets]):
        out = base_path.replace(".png", f"-sheet{i + 1}.png")
        try:
            paths.append(render_sheet_preview(sheet, theme, out))
        except Exception as exc:  # noqa: BLE001 — gallery is additive, never blocking
            log.warning("sheet preview %d failed: %s", i + 1, exc)
    return paths
