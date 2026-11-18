
import json
import os
import re
import sys
from urllib.parse import urljoin, urlparse
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

URL = os.getenv("TARGET_URL", "https://check0ver.net/en/iapps")
OUT = "ashte.json"
MAX_PAGES = 40
TIMEOUT = 12000

BASE = "https://check0ver.net"
DOWNLOAD_WORDS = re.compile(
    r"download|ipa|install|direct|file|mediafire|mega|drive|"
    r"tweak|appstore|download-link",
    re.I
)

SKIP_PATHS = (
    "/en/packages", "/en/pages/", "/login",
    "/register", "/privacy", "/terms"
)


def normalize(url):
    return url.split("#")[0].rstrip("/")


def get_links(page):
    return page.locator("a[href]").evaluate_all("""
        els => els.map(a => ({
            name: (a.innerText || a.title || a.getAttribute('aria-label') || '').trim(),
            link: a.href,
            icon: a.querySelector('img')?.src || null
        }))
    """)


def is_download(item):
    return bool(
        DOWNLOAD_WORDS.search(item["name"] + " " + item["link"])
        or re.search(r"\\.(ipa|plist|zip|deb)(\\?|$)", item["link"], re.I)
    )


def main():
    games = []
    seen = set()
    api_urls = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )

        context = browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
        )

        page = context.new_page()
        page.set_default_timeout(TIMEOUT)

        page.on("response", lambda r:
            api_urls.add(r.url)
            if "json" in (r.headers.get("content-type") or "").lower()
            else None
        )

        print("Opening:", URL, flush=True)

        try:
            page.goto(URL, wait_until="domcontentloaded", timeout=25000)
            page.wait_for_timeout(2000)
        except PlaywrightTimeout:
            print("Main page timeout; continuing...", flush=True)

        # Limited scrolling - no infinite loading
        for _ in range(3):
            page.mouse.wheel(0, 3500)
            page.wait_for_timeout(500)

        links = get_links(page)
        candidates = {}

        for item in links:
            link = normalize(item["link"])
            parsed = urlparse(link)

            if parsed.netloc not in ("check0ver.net", "www.check0ver.net"):
                continue

            if not item["name"] or link == normalize(URL):
                continue

            if any(x in parsed.path.lower() for x in SKIP_PATHS):
                continue

            if parsed.path in ("/", "/en", "/en/iapps"):
                continue

            # Ignore common navigation links
            if item["name"].lower() in (
                "home", "about us", "pricing plans",
                "privacy policy", "terms and conditions",
                "contact us", "login", "register"
            ):
                continue

            candidates[link] = item

        print("Found detail pages:", len(candidates), flush=True)

        for number, (link, item) in enumerate(
            list(candidates.items())[:MAX_PAGES], 1
        ):
            if link in seen:
                continue

            seen.add(link)
            print(f"[{number}/{min(len(candidates), MAX_PAGES)}] {link}", flush=True)

            downloads = []
            icon = item.get("icon")

            try:
                page.goto(
                    link,
                    wait_until="domcontentloaded",
                    timeout=TIMEOUT
                )
                page.wait_for_timeout(700)

                details = get_links(page)

                for detail in details:
                    if is_download(detail):
                        if detail["link"] not in [
                            d["link"] for d in downloads
                        ]:
                            downloads.append({
                                "name": detail["name"] or "Download",
                                "link": detail["link"]
                            })

                # Find the actual app icon
                if not icon:
                    icon = page.locator("img").evaluate_all("""
                        els => {
                            const x = els.find(i =>
                                i.naturalWidth > 80 && i.naturalHeight > 80
                            );
                            return x ? x.src : null;
                        }
                    """)

            except Exception as error:
                print("Page skipped:", str(error)[:150], flush=True)

            games.append({
                "name": item["name"],
                "link": link,
                "icon": icon,
                "downloads": downloads
            })

        browser.close()

    result = {
        "source": URL,
        "count": len(games),
        "download_count": sum(len(x["downloads"]) for x in games),
        "games": games,
        "api": sorted(api_urls)
    }

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print("================================", flush=True)
    print("Saved:", OUT, flush=True)
    print("Apps:", len(games), flush=True)
    print("Downloads:", result["download_count"], flush=True)

    if not games:
        sys.exit("No app pages found. Check the website selectors.")


if __name__ == "__main__":
    main()
