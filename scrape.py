import json
import os
import re
import sys
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright
URL = os.environ.get(
    "TARGET_URL",
    "https://check0ver.net/en/iapps"
)
OUT = "ashte.json"
MAX_PAGES = 500
def main():
    games = []
    api_data = []
    seen = set()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1440, "height": 1000},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"
            )
        )
        page = context.new_page()
        # Capture network requests and JSON responses
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
        # Scroll to load lazy content
        for i in range(15):
            page.mouse.wheel(0, 3500)
            page.wait_for_timeout(1000)
        # Find app cards and their links
        cards = page.evaluate("""() => {
            const result = [];
            const seen = new Set();
            const buttons = [
                ...document.querySelectorAll('a, button')
            ];
            for (const button of buttons) {
                const text = (
                    button.innerText ||
                    button.getAttribute('aria-label') ||
                    ''
                ).trim();
                if (!/download/i.test(text)) continue;
                let parent = button;
                let card = null;
                for (let i = 0; i < 9 && parent; i++) {
                    const heading = parent.querySelector(
                        'h1,h2,h3,h4,h5'
                    );
                    if (
                        heading &&
                        parent.querySelector('img')
                    ) {
                        card = parent;
                        break;
                    }
                    parent = parent.parentElement;
                }
                if (!card) continue;
                const name = (
                    card.querySelector('h1,h2,h3,h4,h5')
                    ?.innerText || ''
                ).trim();
                if (!name || seen.has(name)) continue;
                seen.add(name);
                const links = [
                    ...card.querySelectorAll('a[href]')
                ].map(a => ({
                    text: (a.innerText || '').trim(),
                    href: a.href
                }));
                const image = card.querySelector('img');
                result.push({
                    name,
                    icon: image?.src || null,
                    links,
                    cardText: card.innerText
                });
            }
            return result;
        }""")
        print("Cards found:", len(cards))
        # Visit app detail pages and find download links
        for index, card in enumerate(cards[:MAX_PAGES]):
            name = card["name"]
            detail_links = [
                x["href"] for x in card["links"]
                if x["href"].startswith("http")
                and "check0ver.net" in x["href"]
                and x["href"] != URL
            ]
            detail_url = (
                detail_links[0] if detail_links else None
            )
            downloads = []
            if detail_url:
                try:
                    print(
                        f"[{index + 1}/{len(cards)}] {name}"
                    )
                    page.goto(
                        detail_url,
                        wait_until="domcontentloaded",
                        timeout=60000
                    )
                    page.wait_for_timeout(2500)
                    # Extract download-related links
                    downloads = page.evaluate("""() => {
                        const result = [];
                        const seen = new Set();
                        const elements = [
                            ...document.querySelectorAll(
                                'a[href], button, [data-href], [data-url]'
                            )
                        ];
                        for (const el of elements) {
                            const text = (
                                el.innerText ||
                                el.getAttribute('aria-label') ||
                                ''
                            ).trim();
                            const href =
                                el.href ||
                                el.getAttribute('data-href') ||
                                el.getAttribute('data-url') ||
                                el.getAttribute('formaction');
                            const info = (
                                (text + ' ' + (href || ''))
                            ).toLowerCase();
                            if (
                                !href ||
                                !(
                                    /download|\\.ipa|\\.zip|\\.plist|\\.mobileconfig|\\.deb/.test(info)
                                )
                            ) continue;
                            if (seen.has(href)) continue;
                            seen.add(href);
                            result.push({
                                text,
                                url: new URL(href, location.href).href
                            });
                        }
                        return result;
                    }""")
                except Exception as e:
                    print("Detail error:", e)
            games.append({
                "name": name,
                "link": detail_url,
                "icon": card["icon"],
                "downloads": downloads,
                "details": card["cardText"]
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
    print("\nSaved:", OUT)
    print("Apps:", len(games))
    print("API responses:", len(api_data))
    found = sum(
        len(game["downloads"])
        for game in games
    )
    print("Download links:", found)
    if not games:
        sys.exit("No app cards found")
if __name__ == "__main__":
    main()
