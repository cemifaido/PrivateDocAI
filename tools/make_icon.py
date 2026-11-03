"""Generates assets/privatedoc.ico (shield with a keyhole). Run: python tools/make_icon.py"""
import os

from PIL import Image, ImageDraw

SIZES = (16, 24, 32, 48, 64, 128, 256)


def draw(size: int) -> Image.Image:
    scale = 4  # draw large, then shrink for smooth edges
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m = s * 0.08
    shield = [(s / 2, m), (s - m, s * 0.20), (s - m, s * 0.52), (s / 2, s - m), (m, s * 0.52), (m, s * 0.20)]
    d.polygon(shield, fill=(15, 76, 129, 255))
    inset = s * 0.07
    inner = [(s / 2, m + inset), (s - m - inset, s * 0.23), (s - m - inset, s * 0.51),
             (s / 2, s - m - inset * 1.6), (m + inset, s * 0.51), (m + inset, s * 0.23)]
    d.polygon(inner, fill=(22, 163, 120, 255))
    cx, cy, r = s / 2, s * 0.42, s * 0.11
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255, 255))
    d.polygon([(cx - r * 0.55, cy + r * 0.5), (cx + r * 0.55, cy + r * 0.5),
               (cx + r * 0.9, cy + s * 0.24), (cx - r * 0.9, cy + s * 0.24)], fill=(255, 255, 255, 255))
    return img.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "privatedoc.ico")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    draw(256).save(out, format="ICO", sizes=[(n, n) for n in SIZES])
    print("scritto", out)
