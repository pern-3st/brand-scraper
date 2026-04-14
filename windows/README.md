# Brand Scraper — Windows Install

A self-contained Windows bundle for running the Brand Scraper locally.
If you are the recipient and just want to use the app, open
**[HOW_TO_USE.txt](HOW_TO_USE.txt)** — it has the short, click-by-click version.

This README has more detail: what the scripts do, what can go wrong, and how
to fix it.

---

## What's in this folder

| File | Run it when | What it does |
|---|---|---|
| `setup.bat` | First time only | Installs everything the app needs. Takes 5–10 minutes. |
| `run.bat` | Every time you want to use the app | Starts the app and opens it in your browser. |
| `stop.bat` | When you're done (optional) | Closes the app cleanly. |
| `HOW_TO_USE.txt` | — | Short, non-technical instructions. |
| `README.md` | — | This file. |

You should not need to edit any of these.

---

## System requirements

- Windows 10 (version 1809 or later) or Windows 11
- About 2 GB of free disk space (Python, Node.js, Chromium, and the app)
- An internet connection for the first-time setup

Everything else — Python, Node.js, Chromium, app dependencies — is installed
automatically by `setup.bat`. You do **not** need admin rights in the common
case; Windows may still ask for permission at each install step, which is normal.

---

## First-time setup

1. Make sure this folder is somewhere you can write to — your Desktop or
   Documents folder is fine. Do **not** put it inside "Program Files" or any
   folder that requires admin access.
2. Open the `windows` folder.
3. Double-click **`setup.bat`**.
4. If Windows shows a blue **"Windows protected your PC"** dialog:
   - Click **"More info"**
   - Click **"Run anyway"**
   - This happens because the scripts aren't signed with a certificate.
     The files are safe — they only install public tools and your app's own code.
5. A black terminal window opens. Press any key when prompted.
6. Let it run. You'll see it:
   - Install `uv` (a Python package manager)
   - Install Node.js LTS
   - Download Python 3.14 and the backend's Python libraries
   - Download Chromium (~150 MB — this is the slowest step)
   - Install the frontend's npm packages and build the production bundle
7. When you see **"Setup complete!"**, press any key and close the window.

A hidden file called `.setup_complete` is created inside `windows/` to mark
that setup has run. Don't delete it unless you want to force a re-install.

---

## Every time you want to use the app

1. Double-click **`run.bat`**.
2. Two black terminal windows open, titled **"Brand Scraper Backend"** and
   **"Brand Scraper Frontend"**. Leave them alone — they need to stay open
   while you use the app.
3. Your default browser opens `http://localhost:3000` automatically (within
   about 30 seconds).
4. Use the app in the browser as normal.

If `run.bat` detects that setup hasn't been done yet, it will run `setup.bat`
for you first.

---

## Stopping the app

Either:

- Double-click **`stop.bat`** (cleanest), **or**
- Close the two black terminal windows manually.

`stop.bat` closes the named windows and also frees ports 8000 and 3000 as a
safety net.

---

## Troubleshooting

### "winget is not available"

Your Windows is too old, or the Microsoft Store's "App Installer" component
is missing. Update Windows (Settings → Windows Update) or install "App
Installer" from the Microsoft Store, then re-run `setup.bat`.

### "Port 8000 is already in use" or "Port 3000 is already in use"

Another program is using one of the app's ports. Either:

- Close that other program, or
- Double-click `stop.bat` (it frees the ports), then try `run.bat` again.

If you don't know what's using the port, restarting the computer will clear it.

### "App did not start within 120 seconds"

Look at the two black terminal windows that opened. One of them will show an
error message — screenshot it and send it along when asking for help.

Common causes:
- Antivirus is scanning `node_modules` — wait and try again.
- The OpenRouter API key hasn't been entered yet — open the app, click the
  gear icon, and paste your key. (The key is only required to start a
  scrape, not to launch the app.)

### Setup got interrupted or failed partway

Safe to re-run `setup.bat`. It skips tools that are already installed and
re-does the rest.

### I want to completely re-do setup

Delete the hidden file `windows\.setup_complete`, then double-click
`setup.bat`.

### "Windows protected your PC" dialog keeps appearing

This is SmartScreen. It appears the first time each `.bat` file is run.
Click **"More info" → "Run anyway"**. After the first time, Windows remembers
your choice for that specific file.

---

## What's actually running on your machine

When `run.bat` is active, two processes are listening locally:

| Port | What | Window title |
|---|---|---|
| 8000 | Python backend (FastAPI via `uvicorn`) | Brand Scraper Backend |
| 3000 | Node.js frontend (Next.js `next start`) | Brand Scraper Frontend |

Both listen only on `localhost` — nothing is exposed to your network or the
internet. The app talks to the OpenRouter API over HTTPS for AI features; all
scraping happens in a local headless Chromium browser that `setup.bat`
installed.

---

## Getting help

If something goes wrong:

1. Screenshot the error (the content of any black terminal window, or a
   browser error page).
2. Note what you were doing when it happened.
3. Send both to whoever gave you this bundle.
