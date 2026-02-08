# Daily Wallpaper (GitHub Pages + iOS Shortcuts)

This repo generates a simple daily wallpaper image and publishes it to GitHub Pages. An iPhone Shortcut can download the latest image each morning and set it as your Lock Screen wallpaper.

## What it does

- Generates `latest.png` every day (and optionally an archived `YYYY-MM-DD.png` copy).
- Publishes the generated images to GitHub Pages.
- Your iPhone downloads the image from the Pages URL and sets it as the Lock Screen wallpaper automatically.

Current wallpaper concept:
- A 12-column calendar grid (one column per month).
- Each column contains one circle per day in that month.
- Circles fill top→bottom based on how far we are into the year (with a highlight for “today”).
- The grid is offset downward so it sits below the lock screen clock.

## How it works

1. **GitHub Actions** runs on a schedule (daily) and executes the Python script.
2. The script writes output images to `public/`:
   - `public/latest.png` (stable URL for your phone to fetch)
   - `public/YYYY-MM-DD.png` (optional archive)
3. The workflow uploads `public/` as the GitHub Pages artifact.
4. **GitHub Pages** serves the files at:
   - `https://<username>.github.io/<repo>/latest.png`

## Repo layout

- `generate_wallpaper.py` — generates the wallpaper image(s)
- `requirements.txt` — Python dependencies (Pillow)
- `.github/workflows/*.yml` — scheduled workflow that builds + deploys to GitHub Pages
- `public/` — output directory (published as the site root)

## Local development 

If you want to test the image locally:

```bash
python -m venv .venv
source .venv/bin/activate  # (Windows: .venv\Scripts\activate)
pip install -r requirements.txt
python generate_wallpaper.py
