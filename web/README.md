# FFCS Ranker (web)

Upload FFCS slot PDFs, get faculty ratings merged in and ranked, in the browser.

## Structure
- `public/` — static frontend (HTML/CSS/JS), served directly by Vercel
- `api/parse.py` — Python serverless function (Flask/WSGI) that parses PDFs and matches ratings
- `api/_lib/` — copied from your original repo: `pdf_parser.py`, `normalizer.py`, `matcher.py` (unchanged logic)
- `ratings/ratings-final.xlsx` — bundled ratings data, read at request time

## Deploy to Vercel
1. Push this folder to a new GitHub repo.
2. Vercel → **Add New Project** → **Import Git Repository** → pick the repo.
3. Framework preset: **Other**. No build command needed — Vercel auto-detects `api/*.py` as
   Python functions (via `requirements.txt`) and serves `public/` as static files.
4. Deploy. Done — no environment variables needed.

## Local dev
```
pip install -r requirements.txt
cd api && python -c "from parse import app; app.run(port=5000, debug=True)"
```
Then open `public/index.html` with a simple static server (e.g. `npx serve public`) and change
`fetch("/api/parse")` in `app.js` to `fetch("http://localhost:5000/api/parse")` for local testing.

## Notes
- Matching logic (exact / token-order / initials / fuzzy) is untouched from your CLI version.
- "Not found" faculty are shown with a red pill instead of a rating.
- Ratings are color-coded red→green (0→5) and each PDF's results are sorted by rating, descending.
