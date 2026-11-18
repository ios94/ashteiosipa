import json, os, sys
from playwright.sync_api import sync_playwright

URL = os.environ.get("TARGET_URL", "https://check0ver.net/en/iapps")
LINK_FILTER = os.environ.get("LINK_FILTER", "")  # e.g. "/iapps/" - leave empty to keep all links
OUT = "ashte.json"

def main():
    api_json = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()

        # catch JSON APIs the site loads (most reliable if it exists)
        def on_response(r):
            try:
                if "json" in (r.headers.get("content-type") or ""):
                    api_json.append({"url": r.url, "data": r.json()})
            except Exception:
                pass
        page.on("response", on_response)

        page.goto(URL, wait_until="networkidle", timeout=60000)
        for _ in range(8):  # scroll for lazy loading
            page.mouse.wheel(0, 4000)
            page.wait_for_timeout(800)

        items = page.eval_on_selector_all(
            "a[href]",
            """els => els.map(a => ({
                name: (a.innerText || a.title || '').trim(),
                link: a.href,
                icon: (a.querySelector('img') || {}).src || null
            }))""",
        )
        browser.close()

    seen, games = set(), []
    for it in items:
        if not it["name"] or it["link"] in seen:
            continue
        if LINK_FILTER and LINK_FILTER not in it["link"]:
            continue
        seen.add(it["link"])
        games.append(it)

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"source": URL, "count": len(games), "games": games, "api": api_json},
                  f, ensure_ascii=False, indent=2)
    print(f"Saved {len(games)} items to {OUT}")
    if not games:
        sys.exit("No items found - adjust LINK_FILTER or selectors")

if __name__ == "__main__":
    main()
