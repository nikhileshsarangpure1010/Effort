# Effort Calculation Utility — Report Dashboard

A local desktop dashboard for generating Jira/test.guide-based test execution,
defect, ad-hoc effort, and feature-scope reports. No server, no shared install —
each person clones this repo and runs their own local copy.

This repo intentionally contains **only** the Effort Calculation utility (input
dashboard + report generator + their direct dependencies) — not the other
TMS/TAEE utilities from the same team.

## Quick start (copy-paste)
```powershell
git clone https://cc-github.bmwgroup.net/nagakandukurupartner/Efforts-calculation.git
cd Efforts-calculation
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
# optional, nicer Fluent UI:
pip install -r requirements-qt.txt
```
Then get your own Jira/Test Guide credentials (open `credentials_setup.html` in a
browser, see step 3 under "One-time setup" below) before launching:
```powershell
.venv\Scripts\python.exe report_input_dashboard.py
```

## Prerequisites (install before first run)
- **Python 3.10 or newer** (3.12 recommended — this is what the tool is built and
  tested with). Get it from python.org or your usual internal software portal.
  `tkinter` ships with the standard Windows/macOS Python installer, so no separate
  install is needed for the base UI (on some minimal Linux installs you may need
  an extra OS package, e.g. `python3-tk`, but this tool is primarily used on
  Windows).
- **Git** (to clone the repo and pull future updates).
- **pip packages** — installed via `requirements.txt` (see step 2 below):
  - `requests`, `urllib3` — talk to Jira/test.guide REST APIs.
  - `openpyxl` — optional, only needed for the Feature/SYS.5 Excel export button;
    the HTML report still works fine without it.
  - `requirements-qt.txt` (optional) — `PyQt6` + `PyQt6-Fluent-Widgets`, for the
    nicer Fluent-styled dashboard UI. If skipped, the dashboard automatically
    falls back to the plain built-in Tkinter UI — nothing breaks.
- **Your own Jira personal API token + Test Guide token** — see step 3 below.
  There is no shared/service account; each person authenticates as themselves.

### Explicit pip install commands (equivalent to `pip install -r requirements.txt`)
If you ever need to install the libraries one-by-one instead of from the
requirements files (e.g. checking exact versions, or installing outside a venv):
```powershell
pip install requests==2.34.2 urllib3==2.7.0 openpyxl==3.1.5
```
Optional, only for the Fluent-styled UI:
```powershell
pip install PyQt6==6.11.0 PyQt6-Fluent-Widgets==1.11.3
```

## What's in this repo
- `report_input_dashboard.py` — the input dashboard (contains both the Tkinter UI
  and the PyQt6 Fluent UI; auto-picks Fluent if PyQt6 is installed, otherwise
  falls back to Tkinter). Lets you pick date range, domain, projects, etc. and
  generates a report with one click.
- `report_input_dashboard_pyqt6.py` — a standalone launcher that opens the Qt UI
  from `report_input_dashboard.py` directly (`python report_input_dashboard_pyqt6.py`).
- `test_execution_report_v2.py` — the report generator the dashboard runs under the
  hood. Can also be run standalone from the command line (`--help` for all flags).
- `test_report_input_dashboard.py` — pytest suite covering the dashboard's helper
  functions (not required to run reports, useful if you're changing the code).
- `credentials_setup.html` — a standalone offline form to generate your own
  `credentials.txt` (see step 3 below).
- `requirements.txt` / `requirements-qt.txt` — pinned dependency versions.
- `reports/` — output folder for generated HTML reports (empty in git except for
  a `.gitkeep` placeholder; the tool creates any missing subfolders on first run).

## One-time setup (each colleague does this locally)
1. **Clone this repo**:
   ```
   git clone https://cc-github.bmwgroup.net/nagakandukurupartner/Efforts-calculation.git
   cd Efforts-calculation
   ```
   Never copy someone else's `.venv/`, `credentials.json`, or `credentials.txt` —
   those are machine/person-specific and must be created fresh (see steps 2-3).
2. **Create your own virtual environment** (Python 3.10+, 3.12 recommended):
   ```
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```
   This is all you need — the dashboard runs fine on the built-in Tkinter UI with
   just these core packages (`tkinter` ships with Python itself).

   **Optional — nicer Fluent-styled UI:** if you also want the PyQt6 UI instead of
   the plain Tkinter one, additionally run:
   ```
   pip install -r requirements-qt.txt
   ```
   If this fails or isn't installed, the dashboard automatically falls back to the
   Tkinter UI — nothing breaks, you just get the plainer look.

   If your network requires a proxy for pip, use your usual proxy install method.
3. **Get your own Jira/test.guide credentials.** Open `credentials_setup.html`
   directly in a browser (double-click it, no server needed), fill in your Jira
   email + personal API token + auth mode, and your Test Guide token, then click
   "Download credentials.txt". Move the downloaded file into this same folder
   (beside `report_input_dashboard.py`). The scripts read it automatically; it
   never leaves your machine and is already excluded from git via `.gitignore`.
   - Alternative: set `JIRA_EMAIL`, `JIRA_API_TOKEN`, `JIRA_AUTH_MODE`,
     `TEST_GUIDE_TOKEN` as user environment variables instead of using the file.
4. **Launch the dashboard**:
   ```
   .venv\Scripts\python.exe report_input_dashboard.py
   ```
   It opens the Fluent-styled UI automatically if PyQt6 installed correctly;
   otherwise it prints why and falls back to the plain Tkinter UI.

## Day-to-day use
1. Open the dashboard, pick the date range, domain(s), projects, and which report
   scopes you want (Defect, Resolution, Feature/SYS.5, Rack utilisation, Ad-Hoc, etc.).
2. Click Generate. Progress/console output streams live in the dashboard.
3. When it finishes, the HTML report is saved under `reports/` and can be opened
   directly in any browser or shared as a standalone file (all styling/data is
   embedded, no external dependencies at view-time).

## Getting future updates
Whenever new changes are pushed to this repo, pull them into your existing clone
(no need to re-clone or recreate your `.venv`):
```
git pull
pip install -r requirements.txt
```
Re-run `pip install` after every pull in case dependency versions changed — it's a
no-op if nothing changed. Your `credentials.json`/`credentials.txt` and `.venv/`
are untouched by `git pull` since they're gitignored and never part of the repo.

If you've made local edits and `git pull` reports a conflict, either stash your
changes first (`git stash`, then `git pull`, then `git stash pop`) or ask before
overwriting — don't run `git reset --hard` unless you're sure you want to discard
local changes.

## Notes for sharing
- Never commit or hand off `credentials.json` / `credentials.txt` — everyone needs
  their own Jira/test.guide token. They're excluded via `.gitignore` and will
  never show up in `git status`/`git add .` by accident.
- The `.venv/` folder is not portable between machines — each person builds their
  own with `requirements.txt`.
- `reports/*.html` files are self-contained and safe to share/attach directly, but
  are not committed to git (regenerate locally instead).
