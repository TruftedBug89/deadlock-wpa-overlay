"""Original geometric app artwork, generated without third-party images."""

from pathlib import Path

from PIL import Image, ImageDraw


def create_artwork(destination: Path):
    """Draw a three-card queue mark and return the two build input paths."""
    destination.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((8, 8, 248, 248), radius=54, fill="#0e1419")
    for index, color in enumerate(("#88d5ba", "#537f74", "#304f4b")):
        left = 44 + index * 61
        draw.rounded_rectangle((left, 79, left + 47, 177), radius=11, fill=color)
        draw.rounded_rectangle((left + 10, 139, left + 37, 146), radius=3, fill="#0e1419")
    icon = destination / "app_icon.ico"
    tray = destination / "tray_icon.png"
    image.save(icon, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    image.resize((64, 64), Image.Resampling.LANCZOS).save(tray)
    return icon, tray


if __name__ == "__main__":
    create_artwork(Path(__file__).resolve().parent / "build" / "public_assets")
