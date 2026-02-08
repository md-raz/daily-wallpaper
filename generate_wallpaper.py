from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw

# --------- Output ---------
OUT_DIR = Path("public")
OUT_DIR.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class Style:
    # Canvas: good starting point for modern iPhones
    width: int = 1290
    height: int = 2796

    # Placement: keep grid below the clock
    top_offset: int = 520  # tweak this until it sits where you want
    left_margin: int = 80  # tweak for horizontal centering

    # Circle geometry
    radius: int = 12
    col_gap: int = 24        # space between columns (in pixels, between circle bounding boxes)
    row_gap: int = 10        # space between circles vertically

    # Colors (RGB)
    bg: tuple[int, int, int] = (0, 0, 0)
    past: tuple[int, int, int] = (245, 245, 245)     # days already passed
    future: tuple[int, int, int] = (60, 60, 60)      # days not yet reached
    today: tuple[int, int, int] = (0, 200, 255)      # highlight for today (optional)


def days_in_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def main() -> None:
    style = Style()

    # Use local machine time by default. In GitHub Actions this will be UTC unless you set TZ.
    now = datetime.now()
    year = now.year
    month_today = now.month
    day_today = now.day

    img = Image.new("RGB", (style.width, style.height), style.bg)
    draw = ImageDraw.Draw(img)

    # Precompute layout
    diam = 2 * style.radius
    step_x = diam + style.col_gap
    step_y = diam + style.row_gap

    # Optional: auto-center columns horizontally if you want.
    # Total width is 12 columns of diameter + 11 gaps of col_gap.
    total_grid_width = 12 * diam + 11 * style.col_gap
    left = max(style.left_margin, (style.width - total_grid_width) // 2)

    # Draw 12 columns (Jan..Dec)
    for m in range(1, 13):
        dim = days_in_month(year, m)

        cx = left + (m - 1) * step_x + style.radius  # circle center x

        for d in range(1, dim + 1):
            cy = style.top_offset + (d - 1) * step_y + style.radius  # circle center y

            # Decide color: past / today / future
            if m < month_today:
                color = style.past
            elif m > month_today:
                color = style.future
            else:
                # current month
                if d < day_today:
                    color = style.past
                elif d > day_today:
                    color = style.future
                else:
                    color = style.today

            # Bounding box for the circle
            x0 = cx - style.radius
            y0 = cy - style.radius
            x1 = cx + style.radius
            y1 = cy + style.radius

            draw.ellipse((x0, y0, x1, y1), fill=color)

    # Write stable + archived outputs
    latest_path = OUT_DIR / "latest.png"
    img.save(latest_path, format="PNG")

    #  We omit the archive for now.
    # date_str = now.strftime("%Y-%m-%d")
    # archive_path = OUT_DIR / f"{date_str}.png"
    # img.save(archive_path, format="PNG")

    print(f"Wrote: {latest_path}")


if __name__ == "__main__":
    main()
