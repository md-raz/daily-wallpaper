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
    Renderer       - draws the wallpaper image
    main()         - orchestrates everything + exports
"""

from __future__ import annotations

import calendar
import colorsys
import json
import random
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import Tuple

from PIL import Image, ImageDraw

# ─────────────────────────── Types ────────────────────────────

Color = Tuple[int, int, int]
ColorRGBA = Tuple[int, int, int, int]
Bounds = Tuple[int, int, int, int]  # left, top, right, bottom


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
# Safe zone values are in physical pixels at the native resolution.
# Top safe zone keeps the grid below the lock screen clock + date.
# Bottom safe zone avoids the flashlight/camera buttons + home indicator.
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
    ANALOGOUS = auto()        # Hues within ~30° — calm, cohesive
    COMPLEMENTARY = auto()    # Hues ~180° apart — vibrant contrast
    SPLIT_COMPLEMENTARY = auto()  # Base + two hues flanking complement
    TRIADIC = auto()          # Three hues equally spaced at 120°
    MONOCHROMATIC = auto()    # Single hue, varied saturation/lightness


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


class PaletteFactory:
    """
    Generates random, tasteful 4-color palettes using HSL color theory.

    Design rationale — why HSL-based generation over a fixed list:
      - Fixed lists cycle predictably (N palettes → repeat every N days).
      - HSL constraints guarantee dark BG + readable dots algorithmically.
      - Different harmony types keep things visually interesting day to day.

    Each harmony type constrains hue relationships while saturation and
    lightness are bounded to ensure:
      - Background is always very dark (L ≤ 0.10)
      - "Future" dots are dim but visible against the BG
      - "Past" dots are light enough to clearly read as filled
      - "Today" dot is the most saturated/vivid element
    """

    # Lightness and saturation constraints
    BG_LIGHTNESS = (0.04, 0.10)       # Very dark backgrounds
    BG_SATURATION = (0.20, 0.50)      # Slight color tint in BG
    PAST_LIGHTNESS = (0.70, 0.85)     # Light but not washed out
    PAST_SATURATION = (0.35, 0.65)    # Muted, not garish
    TODAY_LIGHTNESS = (0.50, 0.65)    # Medium — vivid range
    TODAY_SATURATION = (0.70, 0.95)   # High saturation accent
    FUTURE_LIGHTNESS = (0.20, 0.28)   # Just above background
    FUTURE_SATURATION = (0.08, 0.20)  # Nearly neutral

    HARMONY_WEIGHTS = {
        HarmonyType.ANALOGOUS: 3,
        HarmonyType.COMPLEMENTARY: 2,
        HarmonyType.SPLIT_COMPLEMENTARY: 2,
        HarmonyType.TRIADIC: 1,
        HarmonyType.MONOCHROMATIC: 2,
    }

    @classmethod
    def generate(cls) -> Palette:
        """Generate a random tasteful palette."""
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
        """Generate an RGB color within the given HSL bounds."""
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
        """Hues within ±30° — calm, cohesive feel."""
        offset = random.uniform(15, 35)
        bg_hue = base_hue
        past_hue = _wrap_hue(base_hue + offset)
        today_hue = _wrap_hue(base_hue - offset)
        future_hue = base_hue

        return Palette(
            name=f"analogous_{int(base_hue)}",
            bg=cls._make_bg(bg_hue),
            past=cls._make_past(past_hue),
            today=cls._make_today(today_hue),
            future=cls._make_future(future_hue),
        )

    @classmethod
    def _complementary(cls, base_hue: float, harmony: HarmonyType) -> Palette:
        """
        Base hue + 180° complement.
        BG and future use base hue; past and today use the complement
        for strong contrast.
        """
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
        """
        Base hue + two hues flanking the complement (±30° from 180°).
        Gives contrast without the harshness of direct complementary.
        """
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
        """
        Three equally spaced hues at 120° intervals.
        Bold and colorful — used less frequently (lower weight).
        """
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
        """
        Single hue, all variation comes from saturation and lightness.
        Very cohesive, elegant, never clashes.
        """
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

    Design decision — why compute grid params from the content area
    rather than using fixed pixel values:
      The same code must produce good results on 750px (SE) through
      1320px (16 Pro Max) widths. Deriving circle size and spacing
      from the available area means we don't need per-device magic
      numbers.
    """
    cols: int           # Always 12 (months)
    max_rows: int       # Max days in any month (31)
    origin_x: int       # Left edge of first circle center
    origin_y: int       # Top edge of first circle center
    step_x: int         # Horizontal spacing between circle centers
    step_y: int         # Vertical spacing between circle centers
    radius: int         # Circle radius
    island_bounds: Bounds  # Glass island bounding box


class LayoutEngine:
    """
    Computes dot grid geometry to fit within the device's content area.

    The grid has 12 columns (months) and up to 31 rows (days).
    Circles are sized to fill the available width with even spacing,
    capped at a maximum radius to prevent huge dots on large screens.
    """

    MAX_RADIUS = 22         # Cap to prevent oversized dots
    MIN_RADIUS = 10         # Floor for readability
    COL_GAP_RATIO = 1.8     # Gap between columns = radius * this
    ROW_GAP_RATIO = 0.6     # Gap between rows = radius * this
    ISLAND_PADDING = 40     # Padding inside the glass island

    @classmethod
    def compute(cls, device: DeviceProfile, year: int) -> GridConfig:
        left, top, right, bottom = device.content_bounds
        content_width = right - left
        content_height = bottom - top

        max_days = max(calendar.monthrange(year, m)[1] for m in range(1, 13))

        # Solve for radius from available width:
        # total_width = 12 * 2r + 11 * (r * COL_GAP_RATIO)
        # total_width = r * (24 + 11 * COL_GAP_RATIO)
        divisor = 24 + 11 * cls.COL_GAP_RATIO
        radius_from_width = int(content_width / divisor)

        # Also constrain by height:
        # total_height = max_days * (2r + r * ROW_GAP_RATIO)
        # total_height = max_days * r * (2 + ROW_GAP_RATIO)
        row_divisor = max_days * (2 + cls.ROW_GAP_RATIO)
        radius_from_height = int(content_height / row_divisor)

        radius = min(radius_from_width, radius_from_height, cls.MAX_RADIUS)
        radius = max(radius, cls.MIN_RADIUS)

        col_gap = int(radius * cls.COL_GAP_RATIO)
        row_gap = int(radius * cls.ROW_GAP_RATIO)
        diam = 2 * radius
        step_x = diam + col_gap
        step_y = diam + row_gap

        # Center the grid horizontally in the content area
        total_grid_width = 12 * diam + 11 * col_gap
        origin_x = left + (content_width - total_grid_width) // 2 + radius

        # Position grid at top of content area
        origin_y = top + radius

        # Glass island bounds
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


# ─────────────────────────── Renderer ─────────────────────────

@dataclass(frozen=True)
class GlassStyle:
    """Visual parameters for the glassmorphic island."""
    corner_radius: int = 50
    fill_opacity: int = 25          # 0–255
    border_opacity: int = 50        # 0–255
    lighten_fill: int = 30          # How much to lighten BG for fill
    lighten_border: int = 60        # How much to lighten BG for border


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

    def render(self, year: int, month: int, day: int) -> Image.Image:
        """
        Produce the final wallpaper image.

        Args:
            year:  Current year
            month: Current month (1-12)
            day:   Current day of month (1-31)

        Returns:
            PIL Image in RGB mode
        """
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
        """Draw 12 columns of dots, coloring by past/today/future."""
        g = self.grid
        p = self.palette

        for m in range(1, 13):
            days_count = calendar.monthrange(year, m)[1]
            cx = g.origin_x + (m - 1) * g.step_x

            for d in range(1, days_count + 1):
                cy = g.origin_y + (d - 1) * g.step_y

                if m < month or (m == month and d < day):
                    color = p.past
                elif m == month and d == day:
                    color = p.today
                else:
                    color = p.future

                draw.ellipse(
                    (cx - g.radius, cy - g.radius, cx + g.radius, cy + g.radius),
                    fill=color,
                )


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
      - latest.png      (iPhone 12 Pro)
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