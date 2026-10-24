"""Optional developer utility: pip install Pillow, then regenerate extension icons."""
from pathlib import Path

from PIL import Image, ImageDraw

output = Path(__file__).resolve().parents[1] / "extension" / "icons"
output.mkdir(exist_ok=True)
for size in (16, 32, 48, 128):
    scale = 4
    image = Image.new("RGBA", (size * scale, size * scale))
    draw = ImageDraw.Draw(image)
    unit = size * scale / 24
    draw.rounded_rectangle((0, 0, size * scale - 1, size * scale - 1), radius=6 * unit, fill="#354630")
    for points in (((7, 17), (7, 6), (17, 6)), ((7, 11), (14, 11)), ((13, 16), (16, 19), (21, 12))):
        draw.line([(x * unit, y * unit) for x, y in points], fill="#e5eddc", width=max(1, round(1.5 * unit)), joint="curve")
    image.resize((size, size), Image.Resampling.LANCZOS).save(output / f"icon-{size}.png")
