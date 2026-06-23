"""HTML-шаблон карточки рекомендаций и рендер через Playwright."""

from __future__ import annotations
import base64
from pathlib import Path

LOGO_PATH = Path(__file__).parent / "assets" / "vivica_logo.png"


def _logo_b64() -> str:
    if LOGO_PATH.exists():
        with open(LOGO_PATH, "rb") as f:
            return base64.b64encode(f.read()).decode()
    return ""


def build_html(
    style1: str,
    photo_b64_1: str,
    style2: str,
    photo_b64_2: str,
) -> str:
    logo_b64 = _logo_b64()
    logo_tag = (
        f'<img src="data:image/png;base64,{logo_b64}" alt="Vivica" class="logo-img"/>'
        if logo_b64
        else '<span class="logo-text">Vivica</span>'
    )

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    width: 360px;
    height: 480px;
    overflow: hidden;
    background: #e8d8c8;
    display: flex;
    align-items: center;
    justify-content: center;
    font-family: 'NT Somic', sans-serif;
  }}
  .card {{
    width: 360px;
    height: 480px;
    background: #ffecd7;
    overflow: hidden;
    display: flex;
    flex-direction: column;
    border: 1px solid #e9d9c7;
  }}
  .header {{
    padding: 50px 20px 24px;
    text-align: center;
    flex-shrink: 0;
  }}
  .header h1 {{
    font-family: 'NT Somic', sans-serif;
    font-weight: 400;
    font-size: 16px;
    color: #890f1e;
    line-height: 1.3;
    letter-spacing: 0.2px;
  }}
  .spacer-top {{ flex: 1.4; }}
  .products {{
    display: flex;
    gap: 10px;
    padding: 0 16px 12px;
    flex-shrink: 0;
  }}
  .product {{
    flex: 1;
    background: #fff8f0;
    border-radius: 12px;
    overflow: hidden;
    display: flex;
    flex-direction: column;
    border: 0.5px solid #e9d9c7;
  }}
  .product-photo {{
    aspect-ratio: 3 / 4;
    overflow: hidden;
    border-radius: 12px 12px 0 0;
  }}
  .product-photo img {{
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }}
  .product-info {{
    padding: 10px 10px 14px;
    flex-shrink: 0;
  }}
  .product-label {{
    font-family: 'NT Somic', sans-serif;
    font-size: 9px;
    color: #b09070;
    margin-bottom: 3px;
    text-transform: uppercase;
    letter-spacing: 0.8px;
  }}
  .product-name {{
    font-family: 'NT Somic', sans-serif;
    font-size: 12px;
    font-weight: 400;
    color: #890f1e;
    line-height: 1.3;
  }}
  .logo-footer {{
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
  }}
  .logo-img {{
    height: 75px;
    transform: translateY(-15px);
  }}
  .logo-text {{
    font-family: sans-serif;
    font-size: 26px;
    color: #890f1e;
    transform: translateY(-15px);
    display: inline-block;
  }}
</style>
</head>
<body>
<div class="card">
  <div class="header">
    <h1>Выберите свой фасон трусиков</h1>
  </div>
  <div class="spacer-top"></div>
  <div class="products">
    <div class="product">
      <div class="product-photo">
        <img src="data:image/jpeg;base64,{photo_b64_1}" alt=""/>
      </div>
      <div class="product-info">
        <p class="product-label">Комплект белья</p>
        <p class="product-name">с трусиками {style1}</p>
      </div>
    </div>
    <div class="product">
      <div class="product-photo">
        <img src="data:image/jpeg;base64,{photo_b64_2}" alt=""/>
      </div>
      <div class="product-info">
        <p class="product-label">Комплект белья</p>
        <p class="product-name">с трусиками {style2}</p>
      </div>
    </div>
  </div>
  <div class="logo-footer">
    {logo_tag}
  </div>
</div>
</body>
</html>"""


def render_card(html: str, scale: int = 2) -> bytes:
    """Рендерит HTML → PNG через Playwright. scale=2 даёт retina-качество."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(
            viewport={"width": 360, "height": 480},
            device_scale_factor=scale,
        )
        page.set_content(html, wait_until="networkidle")
        png_bytes = page.screenshot(
            clip={"x": 0, "y": 0, "width": 360, "height": 480},
            type="png",
        )
        browser.close()

    from PIL import Image
    import io as _io
    img = Image.open(_io.BytesIO(png_bytes))
    buf = _io.BytesIO()
    img.save(buf, "JPEG", quality=95)
    buf.seek(0)
    return buf.read()
