
import json
import os
import sys
from urllib.parse import urlparse
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

        page = browser.new_page()

        def on_response(response):
            try:
                content_type = response.headers.get(
                    "content-type", ""
                )

                if "json" in content_type.lower():
                    api_data.append({
                        "url": response.url,
                        "data": response.json()
                    })
            except Exception:
                pass

        page.on("response", on_response)

        print("Opening:", URL)

        page.goto(
            URL,
            wait_until="domcontentloaded",
            timeout=90000
        )

        page.wait_for_timeout(5000)

        for _ in range(12):
            page.mouse.wheel(0, 3000)
            page.wait_for_timeout(1000)

        items = page.evaluate("""() => {
            const result = [];

            for (const a of document.querySelectorAll('a[href]')) {
                const href = a.href;
                const name = (
                    a.innerText ||
                    a.title ||
                    ''
                ).trim();

                if (!name || !href) continue;

                const parent = a.closest(
                    'article, [class*="card"], [class*="item"]'
                ) || a.parentElement;

                const img = parent?.querySelector('img');

                result.push({
                    name,
                    link: href,
                    icon: img?.src || null
                });
            }

            return result;
        }""")

        print("Found links:", len(items))

        for item in items:
            link = item["link"]

            if link in seen:
                continue

            seen.add(link)

            if urlparse(link).netloc != urlparse(URL).netloc:
                continue

            downloads = []

            try:
                page.goto(
                    link,
                    wait_until="domcontentloaded",
                    timeout=60000
                )

                page.wait_for_timeout(2000)

                downloads = page.evaluate("""() => {
                    const result = [];
                    const seen = new Set();

                    for (const a of document.querySelectorAll(
                        'a[href], [data-url], [data-href]'
                    )) {
                        const href =
                            a.href ||
                            a.getAttribute('data-url') ||
                            a.getAttribute('data-href');

                        const name = (
                            a.innerText ||
                            a.getAttribute('aria-label') ||
                            ''
                        ).trim();

                        if (!href || seen.has(href)) continue;

                        const value = (
                            href + ' ' + name
                        ).toLowerCase();

                        if (
                            /download|\\.ipa|\\.plist|\\.zip|\\.deb|\\.mobileconfig/.test(value)
                        ) {
                            seen.add(href);

                            result.push({
                                name: name || "Download",
                                url: href
                            });
                        }
                    }

                    return result;
                }""")

            except Exception as e:
                print("Page error:", link, e)

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

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(
            result,
            f,
            ensure_ascii=False,
            indent=2
        )

    total = sum(
        len(x["downloads"]) for x in games
    )

    print("================================")
    print("Saved:", OUT)
    print("Items:", len(games))
    print("Download links:", total)
    print("API responses:", len(api_data))
    print("================================")

    if not games:
        sys.exit("No items found")


if __name__ == "__main__":
    main()
