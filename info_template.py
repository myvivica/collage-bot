"""HTML-шаблон инфографики «фото + буллеты + круглые врезки» и рендер через Playwright.

Формат: 3:4 (WB). Слева — текстовые буллеты и круглые макро-врезки,
справа — основное фото модели. Фон подбирается по цвету краёв фото,
чтобы стык фото и подложки был незаметен.
"""

from __future__ import annotations

import base64
import io
from typing import Sequence

from PIL import Image

W, H = 450, 600  # базовый viewport, рендерится со scale → 1350x1800
SCALE = 3

# Геометрия круглых врезок — в пикселях ИТОГОВОГО изображения (1350x1800).
INSET_SIZE_PX = 510    # диаметр круга
GAP_PX = 42            # единый вертикальный ритм: и между кругами, и между строками текста
INSET_GAP_PX = GAP_PX  # зазор между кругами по вертикали
INSET_AXIS_PX = 312    # X центра общей вертикальной оси, от левого края
INSET_BOTTOM_PX = 156  # отступ нижнего круга от низа


def bg_color_from_photo(data: bytes) -> str:
    """Средний цвет левой кромки фото — используется как фон коллажа."""
    img = Image.open(io.BytesIO(data)).convert("RGB")
    w, h = img.size
    strip = img.crop((0, 0, max(1, w // 12), h)).resize((1, 1), Image.LANCZOS)
    r, g, b = strip.getpixel((0, 0))
    return f"#{r:02x}{g:02x}{b:02x}"


def _luma(hex_color: str) -> float:
    r = int(hex_color[1:3], 16)
    g = int(hex_color[3:5], 16)
    b = int(hex_color[5:7], 16)
    return 0.299 * r + 0.587 * g + 0.114 * b


def build_html(
    photo_b64: str,
    bullets: Sequence[str],
    insets_b64: Sequence[str],
    bg: str = "#dcd5cb",
    text_color: str | None = None,
    focus: int = 50,
) -> str:
    """focus — горизонтальное положение кадра основного фото, 0..100 %."""
    if text_color is None:
        text_color = "#ffffff" if _luma(bg) < 205 else "#4a4a4a"
    # мягкая тень — текст частично лежит поверх фото
    shadow = "rgba(0,0,0,0.28)" if text_color == "#ffffff" else "rgba(255,255,255,0.55)"

    bullets_html = "\n".join(f"<p>{b}</p>" for b in bullets if b.strip())

    insets_html = "\n".join(
        f'<div class="inset"><img src="data:image/jpeg;base64,{b64}" alt=""/></div>'
        for b64 in insets_b64
    )

    size = INSET_SIZE_PX / SCALE
    gap = INSET_GAP_PX / SCALE
    axis = INSET_AXIS_PX / SCALE
    bottom = INSET_BOTTOM_PX / SCALE
    # одна врезка встаёт на место нижней из пары — ось и низ те же

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@300;400&display=swap" rel="stylesheet">
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    width: {W}px; height: {H}px; overflow: hidden;
    font-family: 'Montserrat', sans-serif;
  }}
  .card {{
    position: relative;
    width: {W}px; height: {H}px;
    background: {bg};
    overflow: hidden;
  }}
  .hero {{
    position: absolute;
    right: 0; top: 0;
    width: 61%; height: 100%;
    overflow: hidden;
  }}
  .hero img {{
    width: 100%; height: 100%;
    object-fit: cover; object-position: {focus}% center;
    display: block;
  }}
  .bullets {{
    position: absolute;
    left: 6%; top: 11%;
    width: 68%;
    z-index: 3;
  }}
  .bullets {{
    display: flex;
    flex-direction: column;
    gap: {gap}px;
  }}
  .bullets p {{
    font-weight: 400;
    font-size: 18px;
    line-height: 1.35;
    letter-spacing: 0.2px;
    color: {text_color};
    white-space: nowrap;
    text-shadow: 0 1px 4px {shadow};
  }}
  .insets {{
    position: absolute;
    left: {axis}px;
    bottom: {bottom}px;
    transform: translateX(-50%);
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: {gap}px;
    z-index: 4;
  }}
  .inset {{
    width: {size}px;
    height: {size}px;
    border-radius: 50%;
    overflow: hidden;
    background: #ffffff;
    flex-shrink: 0;
  }}
  .inset img {{
    width: 100%; height: 100%;
    object-fit: cover;
    display: block;
  }}
</style>
</head>
<body>
<div class="card">
  <div class="hero"><img src="data:image/jpeg;base64,{photo_b64}" alt=""/></div>
  <div class="bullets">
{bullets_html}
  </div>
  <div class="insets">
{insets_html}
  </div>
</div>
</body>
</html>"""


# Подгоняет размер шрифта буллетов так, чтобы каждая строка влезала без переноса.
FIT_JS = """
() => {
  const box = document.querySelector('.bullets');
  if (!box) return;
  const limit = box.clientWidth;
  for (let size = 18; size >= 11; size -= 0.5) {
    box.style.fontSize = size + 'px';
    document.querySelectorAll('.bullets p').forEach(p => p.style.fontSize = size + 'px');
    const fits = [...document.querySelectorAll('.bullets p')]
      .every(p => p.scrollWidth <= limit);
    if (fits) return size;
  }
  return 11;
}
"""


def render_card(html: str, scale: int = 3) -> bytes:
    """HTML → PNG через Playwright."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(
            viewport={"width": W, "height": H},
            device_scale_factor=scale,
        )
        page.set_content(html, wait_until="load", timeout=20000)
        page.evaluate("document.fonts.ready")
        page.evaluate(FIT_JS)
        png_bytes = page.screenshot(
            clip={"x": 0, "y": 0, "width": W, "height": H},
            type="png",
            timeout=15000,
        )
        browser.close()

    return png_bytes
