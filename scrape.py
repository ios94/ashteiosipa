
import json
import os
import re
import sys
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

URL = "https://check0ver.net/en"
OUT = "ashte.json"

def main():
    apps = []
    seen = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            accept_downloads=True,
            viewport={"width": 1440, "height": 1100}
        )

        page = context.new_page()

        def get_apps():
            page.goto(URL, wait_until="domcontentloaded",
                      timeout=90000)
            page.wait_for_timeout(5000)

            for _ in range(10):
                page.mouse.wheel(0, 3000)
                page.wait_for_timeout(700)

            return page.locator(
                "a, button"
            ).filter(
                has_text=re.compile(r"^\s*Download\s*$", re.I)
            )

        buttons = get_apps()
        total = buttons.count()

        print("Download buttons:", total)

        for i in range(total):
            try:
                if i > 0:
                    buttons = get_apps()

                if i >= buttons.count():
                    break

                button = buttons.nth(i)

                if not button.is_visible():
                    continue

                # Get app information from its card
                info = button.evaluate("""el => {
                    let node = el;
                    let best = el.parentElement;

                    for (let i = 0; i < 10 && node; i++) {
                        const heading = node.querySelector(
                            'h1,h2,h3,h4,h5'
                        );

                        const img = node.querySelector('img');

                        if (heading && img) {
                            best = node;
                            break;
                        }

                        node = node.parentElement;
                    }

                    const heading = best.querySelector(
                        'h1,h2,h3,h4,h5'
                    );

                    const img = best.querySelector('img');

                    return {
                        name: heading?.innerText?.trim() || '',
                        icon: img?.src || null,
                        card: best.innerText || ''
                    };
                }""")

                name = info["name"]

                if not name:
                    continue

                print(f"\n[{i+1}/{total}] {name}")

                captured = []
                downloaded = []
                opened_pages = []

                def on_request(req):
                    if req.resource_type in (
                        "document", "xhr", "fetch", "other"
                    ):
                        captured.append(req.url)

                page.on("request", on_request)

                def on_new_page(new_page):
                    opened_pages.append(new_page)

                context.on("page", on_new_page)

                # Click the actual Download button
                try:
                    with page.expect_download(timeout=5000) as event:
                        button.click(timeout=10000)

                    download = event.value

                    downloaded.append({
                        "url": download.url,
                        "filename": download.suggested_filename
                    })

                except Exception:
                    pass

                page.wait_for_timeout(5000)

                # Collect redirect and popup destinations
                final_url = page.url

                for new_page in opened_pages:
                    try:
                        new_page.wait_for_timeout(2000)
                        captured.append(new_page.url)

                        if new_page.url != "about:blank":
                            final_url = new_page.url

                    except Exception:
                        pass

                # Get possible download URLs
                candidates = []

                for url in captured:
                    if url and url not in candidates:
                        candidates.append(url)

                for item in downloaded:
                    if item["url"] not in candidates:
                        candidates.append(item["url"])

                # Remove duplicate candidates
                downloads = []

                for url in candidates:
                    if url in (
                        URL,
                        URL + "/"
                    ):
                        continue

                    if url.startswith("blob:"):
                        continue

                    parsed = urlparse(url)

                    if not parsed.scheme.startswith("http"):
                        continue

                    if url not in [x["url"] for x in downloads]:
                        downloads.append({
                            "url": url,
                            "source": "download_click"
                        })

                apps.append({
                    "name": name,
                    "icon": info["icon"],
                    "app_link": final_url,
                    "downloads": downloads,
                    "download_filename": (
                        downloaded[0]["filename"]
                        if downloaded else None
                    )
                })

                print("Captured URLs:", len(downloads))

                for new_page in opened_pages:
                    try:
                        new_page.close()
                    except Exception:
                        pass

                context.remove_listener("page", on_new_page)
                page.remove_listener("request", on_request)

            except Exception as error:
                print("Error:", error)

        browser.close()

    result = {
        "source": URL,
        "count": len(apps),
        "games": apps
    }

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print("\n==========================")
    print("Apps:", len(apps))
    print(
        "Download URLs:",
        sum(len(x["downloads"]) for x in apps)
    )
    print("Saved:", OUT)
    print("==========================")

    if not apps:
        sys.exit("No apps found")

if __name__ == "__main__":
    main()
