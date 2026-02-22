"""
Daily Dot Calendar Wallpaper Generator

Generates a year-progress dot grid wallpaper for iPhone lock screens.
Each run produces a unique, tasteful color palette using HSL color theory
with multiple harmony strategies.

Architecture:
    DeviceProfile  - screen resolution + safe zones
    Palette        - 4-color scheme (bg, past, today, future)
    PaletteFactory - generates random harmonious palettes
    LayoutEngine   - computes dot grid positions respecting safe zones
    Renderer       - draws the wallpaper image (with day-of-week labels)
    main()         - orchestrates everything + exports
"""

from __future__ import annotations

import calendar
import colorsys
import json
import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum, auto
from pathlib import Path
from typing import Tuple

from PIL import Image, ImageDraw, ImageFont

# ─────────────────────────── Types ────────────────────────────

Color = Tuple[int, int, int]
ColorRGBA = Tuple[int, int, int, int]
Bounds = Tuple[int, int, int, int]  # left, top, right, bottom


# ─────────────────────────── Color Utilities ──────────────────

def _hsl_to_rgb(h: float, s: float, l: float) -> Color:
    """
    Convert HSL to RGB tuple.

    Args:
        h: Hue in [0, 360)
        s: Saturation in [0, 1]
        l: Lightness in [0, 1]

    Returns:
        (R, G, B) each in [0, 255]
    """
    # colorsys uses HLS order and hue in [0, 1]
    r, g, b = colorsys.hls_to_rgb(h / 360.0, l, s)
    return (int(r * 255), int(g * 255), int(b * 255))


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _wrap_hue(h: float) -> float:
    """Wrap hue to [0, 360)."""
    return h % 360


def _luminance(c: Color) -> float:
    """
    Relative luminance per ITU-R BT.709.

    Used to decide whether to overlay white or dark text on a colored dot.
    BT.709 weights (0.2126 R, 0.7152 G, 0.0722 B) reflect human perception
    far better than a naive average — green appears much brighter than red
    or blue at the same intensity.
    """
    r, g, b = c[0] / 255.0, c[1] / 255.0, c[2] / 255.0
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _text_color_for_bg(bg: Color) -> Color:
    """Pick white or near-black text for legibility against the dot color."""
    return (20, 20, 20) if _luminance(bg) > 0.4 else (240, 240, 240)


# ─────────────────────────── Device Profiles ──────────────────

@dataclass(frozen=True)
class SafeZone:
    """Region to avoid placing content (in pixels from edge)."""
    top: int = 0
    bottom: int = 0
    left: int = 0
    right: int = 0


@dataclass(frozen=True)
class DeviceProfile:
    """
    Screen resolution and lock screen safe zones.

    Safe zones account for:
    - Top: status bar + clock widget area
    - Bottom: home indicator + flashlight/camera buttons
    - Left/Right: edge padding for visual comfort

    Measurements derived from Apple HIG and empirical testing on
    iOS lock screens. The clock area varies slightly by device but
    ~320pt (converted to pixels at the device scale factor) is safe.
    """
    name: str
    width: int
    height: int
    safe_zone: SafeZone

    @property
    def content_bounds(self) -> Bounds:
        """Usable content area after applying safe zones."""
        return (
            self.safe_zone.left,
            self.safe_zone.top,
            self.width - self.safe_zone.right,
            self.height - self.safe_zone.bottom,
        )


# Target devices.
DEVICE_STANDARD = DeviceProfile(
    name="iPhone 13 Pro",
    width=1170,
    height=2532,
    safe_zone=SafeZone(top=720, bottom=290, left=58, right=58),
)
DEVICE_MAX = DeviceProfile(
    name="iPhone 16 Pro Max (6.9″)",
    width=1320,
    height=2868,
    safe_zone=SafeZone(top=840, bottom=340, left=68, right=68),
)


# ─────────────────────────── Palette Generation ───────────────

class HarmonyType(Enum):
    """Color harmony strategies from color theory."""
    ANALOGOUS = auto()
    COMPLEMENTARY = auto()
    SPLIT_COMPLEMENTARY = auto()
    TRIADIC = auto()
    MONOCHROMATIC = auto()


@dataclass(frozen=True)
class Palette:
    """
    Four-color scheme for the wallpaper.

    bg:     Background fill — always very dark.
    past:   Dots for elapsed days — lighter, muted.
    today:  The current day's dot — vivid accent.
    future: Dots for upcoming days — dim, subtle.
    """
    name: str
    bg: Color
    past: Color
    today: Color
    future: Color

    def to_dict(self) -> dict:
        """Serialize to JSON-friendly dict with hex values."""
        def _hex(c: Color) -> str:
            return "#{:02x}{:02x}{:02x}".format(*c)

        return {
            "palette_name": self.name,
            "colors": {
                role: {"rgb": list(color), "hex": _hex(color)}
                for role, color in [
                    ("background", self.bg),
                    ("past", self.past),
                    ("today", self.today),
                    ("future", self.future),
                ]
            },
        }


class PaletteFactory:
    """
    Generates random, tasteful 4-color palettes using HSL color theory.

    Each harmony type constrains hue relationships while saturation and
    lightness are bounded to ensure:
      - Background is always very dark (L ≤ 0.10)
      - "Future" dots are dim but visible against the BG
      - "Past" dots are light enough to clearly read as filled
      - "Today" dot is the most saturated/vivid element
    """

    BG_LIGHTNESS = (0.04, 0.10)
    BG_SATURATION = (0.20, 0.50)
    PAST_LIGHTNESS = (0.70, 0.85)
    PAST_SATURATION = (0.35, 0.65)
    TODAY_LIGHTNESS = (0.50, 0.65)
    TODAY_SATURATION = (0.70, 0.95)
    FUTURE_LIGHTNESS = (0.20, 0.28)
    FUTURE_SATURATION = (0.08, 0.20)

    HARMONY_WEIGHTS = {
        HarmonyType.ANALOGOUS: 3,
        HarmonyType.COMPLEMENTARY: 2,
        HarmonyType.SPLIT_COMPLEMENTARY: 2,
        HarmonyType.TRIADIC: 1,
        HarmonyType.MONOCHROMATIC: 2,
    }

    @classmethod
    def generate(cls) -> Palette:
        harmony = cls._pick_harmony()
        base_hue = random.uniform(0, 360)
        builder = {
            HarmonyType.ANALOGOUS: cls._analogous,
            HarmonyType.COMPLEMENTARY: cls._complementary,
            HarmonyType.SPLIT_COMPLEMENTARY: cls._split_complementary,
            HarmonyType.TRIADIC: cls._triadic,
            HarmonyType.MONOCHROMATIC: cls._monochromatic,
        }
        return builder[harmony](base_hue, harmony)

    @classmethod
    def _pick_harmony(cls) -> HarmonyType:
        types = list(cls.HARMONY_WEIGHTS.keys())
        weights = list(cls.HARMONY_WEIGHTS.values())
        return random.choices(types, weights=weights, k=1)[0]

    @classmethod
    def _make_color(
        cls, hue: float, sat_range: Tuple[float, float], lit_range: Tuple[float, float]
    ) -> Color:
        s = random.uniform(*sat_range)
        l = random.uniform(*lit_range)
        return _hsl_to_rgb(_wrap_hue(hue), s, l)

    @classmethod
    def _make_bg(cls, hue: float) -> Color:
        return cls._make_color(hue, cls.BG_SATURATION, cls.BG_LIGHTNESS)

    @classmethod
    def _make_past(cls, hue: float) -> Color:
        return cls._make_color(hue, cls.PAST_SATURATION, cls.PAST_LIGHTNESS)

    @classmethod
    def _make_today(cls, hue: float) -> Color:
        return cls._make_color(hue, cls.TODAY_SATURATION, cls.TODAY_LIGHTNESS)

    @classmethod
    def _make_future(cls, hue: float) -> Color:
        return cls._make_color(hue, cls.FUTURE_SATURATION, cls.FUTURE_LIGHTNESS)

    @classmethod
    def _analogous(cls, base_hue: float, harmony: HarmonyType) -> Palette:
        offset = random.uniform(15, 35)
        return Palette(
            name=f"analogous_{int(base_hue)}",
            bg=cls._make_bg(base_hue),
            past=cls._make_past(_wrap_hue(base_hue + offset)),
            today=cls._make_today(_wrap_hue(base_hue - offset)),
            future=cls._make_future(base_hue),
        )

    @classmethod
    def _complementary(cls, base_hue: float, harmony: HarmonyType) -> Palette:
        comp_hue = _wrap_hue(base_hue + 180)
        return Palette(
            name=f"complementary_{int(base_hue)}",
            bg=cls._make_bg(base_hue),
            past=cls._make_past(_wrap_hue(comp_hue + random.uniform(-15, 15))),
            today=cls._make_today(comp_hue),
            future=cls._make_future(base_hue),
        )

    @classmethod
    def _split_complementary(cls, base_hue: float, harmony: HarmonyType) -> Palette:
        split_a = _wrap_hue(base_hue + 150)
        split_b = _wrap_hue(base_hue + 210)
        return Palette(
            name=f"split_comp_{int(base_hue)}",
            bg=cls._make_bg(base_hue),
            past=cls._make_past(split_a),
            today=cls._make_today(split_b),
            future=cls._make_future(base_hue),
        )

    @classmethod
    def _triadic(cls, base_hue: float, harmony: HarmonyType) -> Palette:
        hue_b = _wrap_hue(base_hue + 120)
        hue_c = _wrap_hue(base_hue + 240)
        return Palette(
            name=f"triadic_{int(base_hue)}",
            bg=cls._make_bg(base_hue),
            past=cls._make_past(hue_b),
            today=cls._make_today(hue_c),
            future=cls._make_future(base_hue),
        )

    @classmethod
    def _monochromatic(cls, base_hue: float, harmony: HarmonyType) -> Palette:
        return Palette(
            name=f"monochromatic_{int(base_hue)}",
            bg=cls._make_bg(base_hue),
            past=cls._make_past(base_hue),
            today=cls._make_today(base_hue),
            future=cls._make_future(base_hue),
        )


# ─────────────────────────── Layout Engine ────────────────────

@dataclass(frozen=True)
class GridConfig:
    """
    Computed layout for the dot grid.

    Derived from the content area so the same code works across
    750px (SE) through 1320px (16 Pro Max) widths without
    per-device magic numbers.
    """
    cols: int
    max_rows: int
    origin_x: int
    origin_y: int
    step_x: int
    step_y: int
    radius: int
    island_bounds: Bounds


class LayoutEngine:
    """
    Computes dot grid geometry to fit within the device's content area.

    12 columns (months) × up to 31 rows (days). Circles are sized
    to fill available width with even spacing, capped to prevent
    oversized dots on large screens.
    """

    MAX_RADIUS = 22
    MIN_RADIUS = 10
    COL_GAP_RATIO = 1.8
    ROW_GAP_RATIO = 0.6
    ISLAND_PADDING = 40

    @classmethod
    def compute(cls, device: DeviceProfile, year: int) -> GridConfig:
        left, top, right, bottom = device.content_bounds
        content_width = right - left
        content_height = bottom - top

        max_days = max(calendar.monthrange(year, m)[1] for m in range(1, 13))

        divisor = 24 + 11 * cls.COL_GAP_RATIO
        radius_from_width = int(content_width / divisor)

        row_divisor = max_days * (2 + cls.ROW_GAP_RATIO)
        radius_from_height = int(content_height / row_divisor)

        radius = min(radius_from_width, radius_from_height, cls.MAX_RADIUS)
        radius = max(radius, cls.MIN_RADIUS)

        col_gap = int(radius * cls.COL_GAP_RATIO)
        row_gap = int(radius * cls.ROW_GAP_RATIO)
        diam = 2 * radius
        step_x = diam + col_gap
        step_y = diam + row_gap

        total_grid_width = 12 * diam + 11 * col_gap
        origin_x = left + (content_width - total_grid_width) // 2 + radius

        origin_y = top + radius

        pad = cls.ISLAND_PADDING
        island_left = origin_x - radius - pad
        island_top = origin_y - radius - pad
        island_right = origin_x + 11 * step_x + radius + pad
        island_bottom = origin_y + (max_days - 1) * step_y + radius + pad

        return GridConfig(
            cols=12,
            max_rows=max_days,
            origin_x=origin_x,
            origin_y=origin_y,
            step_x=step_x,
            step_y=step_y,
            radius=radius,
            island_bounds=(island_left, island_top, island_right, island_bottom),
        )


# ─────────────────────────── Day-of-Week Labels ──────────────

# datetime.weekday(): Mon=0 .. Sun=6
DAY_LETTERS = ["M", "T", "W", "T", "F", "S", "S"]


def _build_label_map(year: int, month: int, day: int) -> dict[tuple[int, int], str]:
    """
    Build a mapping of (month, day) → weekday letter for the 7 dots
    centered on today.

    Wrapping strategy:
      Uses timedelta arithmetic on real date objects so month lengths,
      leap years, and month boundaries are handled by the stdlib.
      We then filter to dates within the same year — their month column
      exists in the grid (1–12). The only dates that get clipped are
      those that would fall in a different year:
        - Jan 1–3: some preceding days land in the prior year's Dec
        - Dec 29–31: some following days land in the next year's Jan

      Cross-year wrapping IS possible (Dec's column exists when we're
      in January, and vice versa) but is intentionally excluded because:
        1. Those dots represent a *different* year's context. Labeling
           Dec 31 of last year when viewing Jan 2 of this year would be
           semantically misleading — the dot's past/future coloring is
           relative to the current year.
        2. It affects at most 3 days per year (Jan 1–3 and Dec 29–31),
           so the visual impact is minimal.
        3. Keeping the filter simple (same year only) avoids a class of
           subtle bugs around year transitions.

    Returns:
        Dict mapping (month, day) → single letter string like "M", "W", etc.
    """
    today = date(year, month, day)
    labels: dict[tuple[int, int], str] = {}

    for offset in range(-3, 4):
        d = today + timedelta(days=offset)
        # Only label dots that belong to the current year's grid
        if d.year == year:
            letter = DAY_LETTERS[d.weekday()]
            labels[(d.month, d.day)] = letter

    return labels


# ─────────────────────────── Renderer ─────────────────────────

@dataclass(frozen=True)
class GlassStyle:
    """Visual parameters for the glassmorphic island."""
    corner_radius: int = 50
    fill_opacity: int = 25
    border_opacity: int = 50
    lighten_fill: int = 30
    lighten_border: int = 60


class Renderer:
    """
    Draws the wallpaper to a PIL Image.

    Separated from layout and palette so each piece can be
    tested or swapped independently.
    """

    def __init__(
        self,
        device: DeviceProfile,
        palette: Palette,
        grid: GridConfig,
        glass: GlassStyle | None = None,
    ):
        self.device = device
        self.palette = palette
        self.grid = grid
        self.glass = glass or GlassStyle()
        self._font = self._load_font(grid.radius)

    @staticmethod
    def _load_font(radius: int) -> ImageFont.FreeTypeFont:
        """
        Load a font sized proportionally to dot radius.
        """
        size = max(int(radius * 1.5), 12)
        script_dir = Path(__file__).resolve().parent
        font_paths = [
            # script_dir / "fonts" / "NimbusSanL-BoldCondItal.ttf",
            script_dir / "fonts" / "NimbusSanL-BoldCond.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
        for p in font_paths:
            if Path(p).exists():
                return ImageFont.truetype(str(p), size)
        return ImageFont.load_default()

    def render(self, year: int, month: int, day: int) -> Image.Image:
        """Produce the final wallpaper image."""
        img = Image.new("RGB", (self.device.width, self.device.height), self.palette.bg)
        img = self._draw_glass_island(img)

        draw = ImageDraw.Draw(img)
        self._draw_dots(draw, year, month, day)

        return img

    def _draw_glass_island(self, img: Image.Image) -> Image.Image:
        """Composite a translucent rounded rectangle behind the grid."""
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)

        bg = self.palette.bg
        lighten = self.glass.lighten_fill
        fill: ColorRGBA = (
            min(bg[0] + lighten, 255),
            min(bg[1] + lighten, 255),
            min(bg[2] + lighten, 255),
            self.glass.fill_opacity,
        )

        border_lighten = self.glass.lighten_border
        border: ColorRGBA = (
            min(bg[0] + border_lighten, 255),
            min(bg[1] + border_lighten, 255),
            min(bg[2] + border_lighten, 255),
            self.glass.border_opacity,
        )

        overlay_draw.rounded_rectangle(
            self.grid.island_bounds,
            radius=self.glass.corner_radius,
            fill=fill,
            outline=border,
            width=2,
        )

        img_rgba = img.convert("RGBA")
        result = Image.alpha_composite(img_rgba, overlay)
        return result.convert("RGB")

    def _draw_dots(
        self, draw: ImageDraw.ImageDraw, year: int, month: int, day: int
    ) -> None:
        """
        Draw 12 columns of dots, coloring by past/today/future.

        Day-of-week letters are overlaid on the 7 dots centered on today,
        wrapping into adjacent month columns when today is near a month
        boundary. The label map is precomputed so this loop stays O(365).
        """
        g = self.grid
        p = self.palette

        # Precompute labels — may span up to 3 different months
        labeled_days = _build_label_map(year, month, day)

        for m in range(1, 13):
            days_count = calendar.monthrange(year, m)[1]
            cx = g.origin_x + (m - 1) * g.step_x

            for d in range(1, days_count + 1):
                cy = g.origin_y + (d - 1) * g.step_y

                # Determine dot color
                if m < month or (m == month and d < day):
                    color = p.past
                elif m == month and d == day:
                    color = p.today
                else:
                    color = p.future

                # Draw the dot
                draw.ellipse(
                    (cx - g.radius, cy - g.radius, cx + g.radius, cy + g.radius),
                    fill=color,
                )

                # Overlay day-of-week letter if this dot is labeled
                letter = labeled_days.get((m, d))
                if letter:
                    text_color = _text_color_for_bg(color)
                    bbox = self._font.getbbox(letter)
                    tw = bbox[2] - bbox[0]
                    th = bbox[3] - bbox[1]
                    # Center letter on the dot.
                    # bbox[1] is the top bearing (often negative for ascent),
                    # subtracting it corrects the vertical offset so the
                    # glyph's visual center aligns with the dot's center.
                    tx = cx - tw / 2
                    ty = cy - th / 2 - bbox[1]
                    draw.text((tx, ty), letter, fill=text_color, font=self._font)


# ─────────────────────────── Export ───────────────────────────

def export_palette(palette: Palette, now: datetime, output_dir: Path) -> Path:
    """Save palette metadata as JSON. Returns the written path."""
    meta = {
        "generated_at": now.isoformat(),
        **palette.to_dict(),
    }
    meta_path = output_dir / "palette.json"
    meta_path.write_text(json.dumps(meta, indent=2))
    print(f"  Metadata:  {meta_path}")
    return meta_path


def _render_for_device(
    device: DeviceProfile, palette: Palette, now: datetime
) -> Image.Image:
    """Render a wallpaper for a single device profile."""
    grid = LayoutEngine.compute(device, now.year)
    renderer = Renderer(device, palette, grid)
    return renderer.render(now.year, now.month, now.day)


# ─────────────────────────── CLI ──────────────────────────────

def main() -> None:
    """
    Entry point. Generates three files in the output directory:
      - latest.png      (iPhone 13 Pro)
      - latest_max.png  (iPhone 16 Pro Max)
      - palette.json    (shared palette metadata)
    """
    import os

    now = datetime.now()
    output_dir = Path(os.environ.get("OUTPUT_DIR", "public"))
    output_dir.mkdir(parents=True, exist_ok=True)

    palette = PaletteFactory.generate()
    print(f"Palette: {palette.name}")
    print(
        f"  BG={palette.bg}  Past={palette.past}  "
        f"Today={palette.today}  Future={palette.future}"
    )

    # Standard size
    print(f"\nGenerating for {DEVICE_STANDARD.name}")
    img = _render_for_device(DEVICE_STANDARD, palette, now)
    path = output_dir / "latest.png"
    img.save(path, format="PNG", optimize=True)
    print(f"  Wrote: {path}")

    # Max size
    print(f"\nGenerating for {DEVICE_MAX.name}")
    img_max = _render_for_device(DEVICE_MAX, palette, now)
    path_max = output_dir / "latest_max.png"
    img_max.save(path_max, format="PNG", optimize=True)
    print(f"  Wrote: {path_max}")

    # Shared palette
    export_palette(palette, now, output_dir)

    print("\nDone.")


if __name__ == "__main__":
    main()