from datetime import datetime
from pathlib import Path

from PIL import Image

# Output directory that we will publish to GitHub Pages
OUT_DIR = Path("public")
OUT_DIR.mkdir(parents=True, exist_ok=True)

def main() -> None:
    # iPhone-ish resolution (safe starting point).
    # You can change later once you test on your device.
    width, height = 1290, 2796

    # Blank black image (RGB). Change color later if you want.
    img = Image.new("RGB", (width, height), color=(0, 0, 0))

    # Always write a stable filename for the Shortcut to fetch
    latest_path = OUT_DIR / "latest.png"
    img.save(latest_path, format="PNG")

    # Optional: also save a dated archive copy (handy for debugging)
    date_str = datetime.now().strftime("%Y-%m-%d")
    archive_path = OUT_DIR / f"{date_str}.png"
    img.save(archive_path, format="PNG")

    print(f"Wrote: {latest_path} and {archive_path}")

if __name__ == "__main__":
    main()
