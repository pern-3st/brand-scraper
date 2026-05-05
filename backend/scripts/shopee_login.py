"""
Open the persistent shopee_sg Chrome profile so the user can log in.

The login cookies are written into the same profile directory used by
ShopeeScraper, the enrichment pipeline, and the spike scripts
(``backend/data/browser_profiles/shopee_sg``). Once you've logged in here,
subsequent scrapes/spikes reuse the session until Shopee expires it (which
happens periodically, especially after anti-bot challenges).

Run:
    cd backend && uv run python scripts/shopee_login.py

Then:
    1. The Chrome window opens at shopee.sg.
    2. Click the login button in the top-right and log in.
    3. Come back to the terminal and press Enter to close the session
       cleanly (cookies are flushed to disk on close).
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.platforms.shopee._session import PROFILE_DIR, launch_persistent_context


async def main() -> None:
    print(f"Profile dir: {PROFILE_DIR}")
    print("Opening shopee.sg ...")
    async with launch_persistent_context() as (_p, context):
        page = await context.new_page()
        try:
            await page.goto("https://shopee.sg/", wait_until="domcontentloaded")
        except Exception as exc:
            print(f"[warn] initial nav failed: {exc} — you can still navigate manually")
        print()
        print("Log in via the open Chrome window.")
        print("When done, press Enter here to save the session and close.")
        # Run blocking input() off the event loop so playwright keeps ticking.
        await asyncio.get_event_loop().run_in_executor(None, input)
        print("Closing — cookies will be persisted to the profile.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[interrupted]")
        sys.exit(130)
