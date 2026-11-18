import json
import os
import re
import sys
from urllib.parse import urljoin, urlparse
from playwright.sync_api import sync_playwright
URL = os.environ.get(
    "TARGET_URL",
    "https://check0ver.net/en/iapps"
)
OUT = "ashte.json"
def main():
    games = []
    api_data = []
    seen = set()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1440, "height": 1000}
        )
        page = context.new_page()
        def on_response(response):
            try:
                content_type = response.headers.get(
                    "content-type", ""
                )
                if "json" in content_type.lower():
                    data = response.json()
                    api_data.append({
                        "url": response.url,
                        "data": data
                    })
            except Exception:
                pass
        page.on("response", on_response)
        print("Opening website:", URL)
        page.goto(
            URL,
            wait_until="domcontentloaded",
            timeout=90000
        )
        page.wait_for_timeout(5000)
        # Load lazy content
        for _ in range(15):
            page.mouse.wheel(0, 3000)
            page.wait_for_timeout(1000)
        # Collect app-related links
        cards = page.evaluate("""() => {
            const output = [];
            const seen = new Set();
            const links = document.querySelectorAll('a[href]');
            for (const a of links) {
                const href = a.href;
                const text = (a.innerText || '').trim();
                if (!href || !text) continue;
                const parent = a.closest(
                    'article, [class*="card"], [class*="item"]'
                ) || a.parentElement;
                const title = parent?.querySelector(
                    'h1,h2,h3,h4,h5'
                );
                const image = parent?.querySelector('img');
                const name = (
                    title?.innerText || text
                ).trim();
                if (!name || seen.has(href)) continue;
                seen.add(href);
                output.push({
                    name: name,
                    link: href,
                    icon: image?.src || null
                });
            }
            return output;
        }""")
        print("Links found:", len(cards))
        for index, item in enumerate(cards):
            link = item["link"]
            parsed = urlparse(link)
            # Only inspect pages on the target website
            if parsed.netloc != urlparse(URL).netloc:
                continue
            if link in seen:
                continue
            seen.add(link)
            downloads = []
            try:
                print(
                    f"Checking {index + 1}: {item['name']}"
                )
                page.goto(
                    link,
                    wait_until="domcontentloaded",
                    timeout=60000
                )
                page.wait_for_timeout(2500)
                downloads = page.evaluate("""() => {
                    const output = [];
                    const seen = new Set();
                    const elements = document.querySelectorAll(
                        'a[href], [data-url], [data-href]'
                    );
                    for (const el of elements) {
                        const href =
                            el.href ||
                            el.getAttribute('data-url') ||
                            el.getAttribute('data-href');
                        const text = (
                            el.innerText ||
                            el.getAttribute('aria-label') ||
                            ''
                        ).trim();
                        if (!href || seen.has(href)) continue;
                        const value = (
                            href + ' ' + text
                        ).toLowerCase();
                        if (
                            /download|\\.ipa|\\.plist|\\.mobileconfig|\\.deb|\\.zip/.test(value)
                        ) {
                            seen.add(href);
                            output.push({
                                name: text || 'Download',
                                url: new URL(
                                    href,
                                    location.href
                                ).href
                            });
                        }
                    }
                    return output;
                }""")
            except Exception as error:
                print("Page error:", error)
            games.append({
                "name": item["name"],
                "link": link,
                "icon": item["icon"],
                "downloads": downloads
            })
        browser.close()
    result = {
        "source": URL,
        "count": len(games),
        "games": games,
        "api": api_data
    }
    temp = OUT + ".tmp"
    with open(temp, "w", encoding="utf-8") as file:
        json.dump(
            result,
            file,
            ensure_ascii=False,
            indent=2
        )
    os.replace(temp, OUT)
    total_downloads = sum(
        len(game["downloads"])
        for game in games
    )
    print("--------------------------------")
    print("Saved:", OUT)
    print("Total items:", len(games))
    print("Download links:", total_downloads)
    print("API responses:", len(api_data))
    print("--------------------------------")
    if not games:
        sys.exit("No items found")
if __name__ == "__main__":
    main()
