"""
Battery icon renderer and font loader.
"""
from PIL import Image, ImageDraw, ImageFont, ImageFilter

from . import config
from . import system


def load_font(size):
    """Load best available font at given point size."""
    for name in ("segoeuisb.ttf", "segoeuib.ttf", "segoeui.ttf", "arialbd.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            pass
    return ImageFont.load_default()


def render_battery(W, H, bat, label=None, dark=True):
    """Render the battery widget icon at W×H using RENDER_SCALE× supersampling."""
    from . import battery as bat_mod

    S      = config.RENDER_SCALE
    sw, sh = W * S, H * S
    img    = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
    d      = ImageDraw.Draw(img)

    if bat is None:
        fnt = load_font(config.FONT_SIZE * S)
        d.text((sw // 2, sh // 2), "N/A", font=fnt, fill=(136, 136, 136, 255), anchor="mm")
        return img.resize((W, H), Image.LANCZOS).filter(
            ImageFilter.UnsharpMask(radius=0.5, percent=180, threshold=0))

    pct     = bat.percent
    plugged = bat.power_plugged
    if label is None:
        time_s = bat_mod.format_time(bat.secsleft)
        label  = time_s if time_s else f"{pct:.0f}%"

    cw = config.COLORS_WIDGET
    if plugged:
        fill_col = cw["fill_charging"]
    elif pct <= config.LOW_PCT:
        fill_col = cw["fill_low"]
    elif system.get_power_mode() == "Battery Saver":
        fill_col = cw["fill_saver"]
    else:
        fill_col = cw["fill_normal"]

    nub_w  = 5 * S
    bx0, by0 = 2 * S, 2 * S
    bx1, by1 = sw - 2 * S - nub_w, sh - 2 * S
    body_w   = bx1 - bx0
    body_h   = by1 - by0
    r        = config.CORNER_RADIUS * S

    _c       = config.COLORS_DARK if dark else config.COLORS_LIGHT
    body_bg  = _c["widget_body"]    + (255,)
    nub_col  = _c["widget_nub"]     + (255,)
    outline  = _c["widget_outline"] + (255,)
    text_col = _c["widget_text"]    + (255,)

    nub_h  = max(4 * S, body_h // 3)
    nub_y0 = by0 + (body_h - nub_h) // 2
    d.rounded_rectangle([bx1, nub_y0, bx1 + nub_w, nub_y0 + nub_h],
                        radius=min(r, nub_w // 2), fill=nub_col)

    d.rounded_rectangle([bx0, by0, bx1, by1], radius=r, fill=body_bg)

    pad        = config.FILL_PADDING * S
    rext       = config.FILL_RIGHT_EXTEND * S
    fill_max_w = max(1, body_w - 2 * pad)
    fill_w     = max(1, int(fill_max_w * pct / 100))
    fill_x1    = min(bx0 + pad + fill_w + rext, bx1 - pad)
    d.rounded_rectangle([bx0 + pad, by0 + pad, fill_x1, by1 - pad],
                        radius=max(1, r - pad) if pad > 0 else r, fill=fill_col)

    d.rounded_rectangle([bx0, by0, bx1, by1], radius=r,
                        outline=outline, width=config.OUTLINE_WIDTH * S)

    fnt = load_font(config.FONT_SIZE * S)
    d.text((bx0 + body_w // 2, by0 + body_h // 2), label,
           font=fnt, fill=text_col, anchor="mm")

    return img.resize((W, H), Image.LANCZOS).filter(
        ImageFilter.UnsharpMask(radius=0.5, percent=180, threshold=0))
