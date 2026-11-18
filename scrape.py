
import json
import os
import re
import sys
from urllib.parse import urljoin, urlparse
from playwright.sync_api import sync_playwright

BASE = "https://check0ver.net"
URL = os.getenv("TARGET_URL", BASE + "/en")
OUT = "ashte.json"

GAME_WORDS = re.compile(
    r"\b(game|games|paid games|gaming)\b|"
    r"العاب|ألعاب|لعبة|ياري",
    re.I
)

DOWNLOAD_WORDS = re.compile(
    r"download|تحميل|تنزيل|ipa|install",
    re.I
)

def clean(url):
    return url.split("#")[0].rstrip("/")

def get_links(page):
    return page.locator("a[href]").evaluate_all("""
    els => els.map(a => ({
        name: (a.innerText || a.title ||
               a.getAttribute('aria-label') || '').trim(),
        link: a.href,
        icon: a.querySelector('img')?.src || null
    }))
    """)

def get_categories(page):
    found = {}

    for item in get_links(page):
        if not item["name"]:
            continue

        if GAME_WORDS.search(item["name"]):
            if "/iapps" in item["link"]:
                found[clean(item["link"])] = item["name"]

    return found

def get_game_cards(page):
    return page.locator("a[href]").evaluate_all("""
    els => {
      const output = [];

      for (const a of els) {
        const name = (a.innerText || a.title || '').trim();
        const href = a.href;

        if (!name || !href.includes('/iapps/')) continue;

        let node = a;

        for (let i = 0; i < 6 && node.parentElement; i++) {
          node = node.parentElement;

          const text = node.innerText || '';

          if (/Download/i.test(text) &&
              text.length < 12000) {
            const img = node.querySelector('img');

            const links = [...node.querySelectorAll('a[href]')]
              .map(x => ({
                name: (x.innerText || x.title || 'Download').trim(),
                link: x.href
              }));

            output.push({
              name: name,
              link: href,
              icon: img ? img.src : null,
              downloads: links.filter(x =>
                /download|تحميل|تنزيل/i.test(x.name + ' ' + x.link)
              )
            });

            break;
          }
        }
      }

      return output;
    }
    """)

def main():
    games = {}
    categories = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox"]
        )

        page = browser.new_page()
        page.set_default_timeout(15000)

        print("Opening website...", flush=True)

        page.goto(URL, wait_until="domcontentloaded")
        page.wait_for_timeout(2500)

        # Discover game categories
        page.goto(BASE + "/en/categories",
                  wait_until="domcontentloaded")
        page.wait_for_timeout(2000)

        categories.update(get_categories(page))

        # Also discover categories from homepage
        page.goto(URL, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)

        categories.update(get_categories(page))

        # Known Games category from the website
        categories[
            BASE + "/en/iapps?filter[inCategories][0]="
            "9c60f563-1983-42f0-8882-a26207bd4aaf"
        ] = "Games"

        print("Game categories:", len(categories), flush=True)

        for category_url, category_name in categories.items():

            print("Category:", category_name, flush=True)

            for page_number in range(1, 31):

                target = category_url

                if page_number > 1:
                    separator = "&" if "?" in target else "?"
                    target += separator + "page=" + str(page_number)

                try:
                    page.goto(
                        target,
                        wait_until="domcontentloaded",
                        timeout=30000
                    )
                    page.wait_for_timeout(1200)

                    cards = get_game_cards(page)

                    if not cards:
                        break

                    for game in cards:
                        link = clean(game["link"])

                        if link not in games:
                            games[link] = {
                                "name": game["name"],
                                "link": link,
                                "icon": game["icon"],
                                "category": category_name,
                                "downloads": []
                            }

                        for download in game["downloads"]:
                            if download["link"] not in [
                                x["link"]
                                for x in games[link]["downloads"]
                            ]:
                                games[link]["downloads"].append(download)

                    print(
                        "Page", page_number,
                        "Games:", len(games),
                        flush=True
                    )

                except Exception as e:
                    print("Page error:", str(e)[:150], flush=True)
                    break

        # Inspect each game detail page for download links
        for number, game in enumerate(list(games.values()), 1):

            print(
                f"Checking {number}/{len(games)}: {game['name']}",
                flush=True
            )

            try:
                page.goto(
                    game["link"],
                    wait_until="domcontentloaded",
                    timeout=30000
                )
                page.wait_for_timeout(900)

                details = get_links(page)

                for item in details:
                    if DOWNLOAD_WORDS.search(
                        item["name"] + " " + item["link"]
                    ):
                        if item["link"] not in [
                            x["link"] for x in game["downloads"]
                        ]:
                            game["downloads"].append({
                                "name": item["name"] or "Download",
                                "link": item["link"]
                            })

                if not game["icon"]:
                    game["icon"] = page.locator(
                        "img"
                    ).evaluate_all("""
                    els => {
                      const img = els.find(x =>
                        x.naturalWidth > 80 &&
                        x.naturalHeight > 80
                      );
                      return img ? img.src : null;
                    }
                    """)

            except Exception as e:
                print("Detail error:", str(e)[:120], flush=True)

        browser.close()

    result = {
        "source": URL,
        "count": len(games),
        "download_count": sum(
            len(x["downloads"]) for x in games.values()
        ),
        "games": list(games.values())
    }

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print("==========================")
    print("Games:", result["count"])
    print("Downloads:", result["download_count"])
    print("Saved:", OUT)

    if not games:
        sys.exit("No games found!")

if __name__ == "__main__":
    main()
