from pathlib import Path
from PIL import Image, ImageDraw

root = Path(__file__).resolve().parents[1]
(root / "assets").mkdir(exist_ok=True)
image = Image.new("RGBA", (256, 256))
draw = ImageDraw.Draw(image)
draw.rounded_rectangle((8, 8, 248, 248), 44, fill="#1769c2")
draw.rounded_rectangle((56, 76, 168, 218), 10, outline="white", width=9)
draw.rounded_rectangle((88, 40, 204, 182), 10, fill="#1769c2", outline="white", width=9)
draw.ellipse((180, 180, 250, 250), fill="#24b568", outline="white", width=7)
image.save(root / "assets" / "clipbridge.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
