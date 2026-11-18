
import json
import os
import re
import sys
from collections import deque
from urllib.parse import urljoin, urlparse, urldefrag

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

URL = os.getenv("TARGET_URL", "https://check0ver.net/en/iapps")
OUT = "ashte.json"

BASE_DOMAIN = "check0ver.net"
MAX_PAGES = 50
MAX_DEPTH = 3
TIMEOUT = 8000

DOWNLOAD_WORDS = re.compile(
    r"download|ipa|install|direct|file|mediafire|mega|drive|"
    r"tweak|appstore|telegram|download-link",
    re.I
)

FILE_EXTENSIONS = re.compile(
    r"\.(ipa|plist|zip|deb|dylib|apk)(?:\?|$)",
    re.I
)

SKIP_PATHS = (
    "/login", "/register", "/privacy",
    "/terms", "/packages", "/pages/",
    "/contact", "/account"
)

NAV_NAMES = {
    "home", "about us", "pricing plans",
    "privacy policy", "terms and conditions",
    "contact us", "login", "register"
}


def normalize(url):
    url = urldefrag(url)[0]
    return url.rstrip("/")


def same_domain(url):
    host = (urlparse(url).hostname or "").lower()
    return host in (BASE_DOMAIN, "www." + BASE_DOMAIN)


def valid_internal(url):
    parsed = urlparse(url)

    if not same_domain(url):
        return False

    path = parsed.path.lower()

    if any(x in path for x in SKIP_PATHS):
        return False

    if re.search(
        r"\.(png|jpg|jpeg|webp|svg|css|js|woff2?|ico)$",
        path,
        re.I
    ):
        return False

    return path.startswith("/en") or path == "/"


def get_links(page):
    return page.locator("a[href]").evaluate_all("""
        els => els.map(a => ({
            name: (
                a.innerText ||
                a.title ||
                a.getAttribute('aria-label') ||
                a.querySelector('img')?.alt ||
                ''
            ).trim().replace(/\\s+/g, ' '),

            link: a.href,

            icon:
                a.querySelector('img')?.src ||
                null
        }))
    """)


def is_download(item):
    name = item.get("name", "")
    link = item.get("link", "")

    return bool(
        DOWNLOAD_WORDS.search(name)
        or FILE_EXTENSIONS.search(link)
    )


def add_download(downloads, item):
    link = normalize(item["link"])

    if not link or link.startswith("javascript:"):
        return

    if any(x["link"] == link for x in downloads):
        return

    downloads.append({
        "name": item.get("name") or "Download",
        "link": link
    })


def get_icon(page, fallback=None):
    if fallback:
        return fallback

    try:
        return page.locator("img").evaluate_all("""
            els => {
                const image = els.find(i =>
                    i.naturalWidth >= 80 &&
                    i.naturalHeight >= 80
                );

                if (image) return image.src;

                const meta = document.querySelector(
                    'meta[property="og:image"]'
                );

                return meta ? meta.content : null;
            }
        """)
    except Exception:
        return None


def main():

    games = []
    visited = set()
    api_urls = set()
    game_map = {}

    queue = deque([(normalize(URL), 0)])

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage"
            ]
        )

        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )

        page = context.new_page()
        page.set_default_timeout(TIMEOUT)

        def capture_api(response):
            try:
                content_type = response.headers.get(
                    "content-type", ""
                ).lower()

                if "json" in content_type:
                    api_urls.add(response.url)

            except Exception:
                pass

        page.on("response", capture_api)

        print("Starting scraper:", URL, flush=True)

        while queue and len(visited) < MAX_PAGES:

            current, depth = queue.popleft()
            current = normalize(current)

            if current in visited:
                continue

            if not valid_internal(current):
                continue

            visited.add(current)

            print(
                f"[{len(visited)}/{MAX_PAGES}] "
                f"Depth {depth}: {current}",
                flush=True
            )

            try:
                page.goto(
                    current,
                    wait_until="domcontentloaded",
                    timeout=TIMEOUT
                )

                page.wait_for_timeout(300)

            except PlaywrightTimeout:
                print("Timeout, trying available content...", flush=True)

            except Exception as error:
                print(
                    "Page error:",
                    str(error)[:120],
                    flush=True
                )
                continue

            try:
                # Limited scrolling for lazy-loaded content
                if depth == 0:
                    for _ in range(2):
                        page.mouse.wheel(0, 2500)
                        page.wait_for_timeout(300)

                links = get_links(page)

                title = page.title() or ""
                page_name = (
                    page.locator("h1").first.inner_text(
                        timeout=2000
                    ).strip()
                    if page.locator("h1").count()
                    else title
                )

                page_downloads = []

                # Collect downloads and discover new pages
                for item in links:

                    link = normalize(item["link"])
                    name = item["name"]

                    if is_download(item):
                        add_download(page_downloads, item)

                    if not same_domain(link):
                        continue

                    if not valid_internal(link):
                        continue

                    if link == current or link in visited:
                        continue

                    if depth < MAX_DEPTH:
                        if not any(
                            queued[0] == link for queued in queue
                        ):
                            queue.append((link, depth + 1))

                    if name.lower() in NAV_NAMES:
                        continue

                    if link not in game_map:
                        game_map[link] = {
                            "name": name or page_name or "Unknown",
                            "link": link,
                            "icon": item.get("icon"),
                            "downloads": []
                        }

                # Attach downloads found on the current page
                if current in game_map:

                    game = game_map[current]

                    if not game["icon"]:
                        game["icon"] = get_icon(page)

                    for download in page_downloads:
                        add_download(
                            game["downloads"],
                            download
                        )

                # Save useful content from the starting page too
                elif current != normalize(URL):

                    if current not in game_map:
                        game_map[current] = {
                            "name": page_name or title or "Unknown",
                            "link": current,
                            "icon": get_icon(page),
                            "downloads": page_downloads
                        }

                # Also check buttons and download elements
                try:
                    buttons = page.locator(
                        "button, [role='button']"
                    ).evaluate_all("""
                        els => els.map(e => ({
                            name: (e.innerText || '').trim(),
                            link:
                                e.getAttribute('href') ||
                                e.getAttribute('data-url') ||
                                e.getAttribute('data-href') ||
                                ''
                        }))
                    """)

                    for button in buttons:
                        if button["link"]:
                            item = {
                                "name": button["name"],
                                "link": urljoin(
                                    current,
                                    button["link"]
                                )
                            }

                            if is_download(item):
                                if current in game_map:
                                    add_download(
                                        game_map[current]["downloads"],
                                        item
                                    )

                except Exception:
                    pass

            except Exception as error:
                print(
                    "Extraction error:",
                    str(error)[:150],
                    flush=True
                )

        browser.close()

    games = list(game_map.values())

    # Remove duplicate entries
    unique = {}

    for game in games:
        link = normalize(game["link"])
        if link not in unique:
            unique[link] = game

    games = list(unique.values())

    result = {
        "source": URL,
        "pages_scanned": len(visited),
        "count": len(games),
        "download_count": sum(
            len(g["downloads"]) for g in games
        ),
        "games": games,
        "api": sorted(api_urls)
    }

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(
            result,
            f,
            ensure_ascii=False,
            indent=2
        )

    print("--------------------------------", flush=True)
    print("Saved:", OUT, flush=True)
    print("Pages scanned:", len(visited), flush=True)
    print("Apps/pages:", len(games), flush=True)
    print("Downloads:", result["download_count"], flush=True)
    print("API endpoints:", len(api_urls), flush=True)
    print("--------------------------------", flush=True)

    if not games:
        sys.exit("No pages found!")


if __name__ == "__main__":
    main()
