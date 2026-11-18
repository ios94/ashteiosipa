
import json
import os
import re
import sys
from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse
from playwright.sync_api import sync_playwright

BASE = "https://check0ver.net"
URL = os.getenv("TARGET_URL", BASE + "/en")
OUT = "ashte.json"

GAME_ID = "9c60f563-1983-42f0-8882-a26207bd4aaf"

GAME_WORDS = re.compile(
    r"games?|paid games|arcade games|nintendo|switch|العاب|ألعاب|ياري",
    re.I
)

DOWNLOAD_WORDS = re.compile(
    r"download|تحميل|تنزيل|install",
    re.I
)


def absolute(url):
    return urljoin(BASE, url) if url else ""


def clean(url):
    return url.split("#")[0].strip()


def extract_categories(page):
    result = {}

    links = page.locator("a[href]").evaluate_all("""
    els => els.map(a => ({
      text: (a.innerText || a.title || '').trim(),
      href: a.href
    }))
    """)

    for item in links:
        name = item["text"]
        href = clean(item["href"])

        if GAME_WORDS.search(name) and "/iapps" in href:
            result[href] = name

    result[
        BASE + "/en/iapps?filter[inCategories][0]=" + GAME_ID
    ] = "Games"

    return result


def extract_cards(page, category):
    """
    Find cards by their Download button and surrounding content.
    Does not assume that game detail URLs contain /iapps/.
    """
    return page.evaluate("""
    () => {
      const output = [];
      const seen = new Set();

      const downloadElements = [...document.querySelectorAll(
        'a[href], button, [role="button"]'
      )].filter(el => {
        const text = (el.innerText || el.textContent || '').trim();
        return /download|تحميل|تنزيل/i.test(text);
      });

      for (const button of downloadElements) {
        let card = button;
        let best = null;

        for (let i = 0; i < 9 && card; i++) {
          const text = (card.innerText || '').trim();

          const headings = [...card.querySelectorAll(
            'h1,h2,h3,h4,h5,h6'
          )];

          const title = headings
            .map(h => (h.innerText || '').trim())
            .find(t => t.length > 1 && t.length < 180);

          const anchors = [...card.querySelectorAll('a[href]')];

          if (
            title &&
            text.length < 7000 &&
            anchors.length > 0
          ) {
            best = {
              title,
              text,
              html: card,
              anchors
            };
            break;
          }

          card = card.parentElement;
        }

        if (!best) continue;

        const title = best.title;
        if (seen.has(title)) continue;
        seen.add(title);

        const links = best.anchors.map(a => ({
          text: (a.innerText || a.title || '').trim(),
          href: a.href,
          image: a.querySelector('img')?.src || null
        }));

        const downloadLinks = links.filter(x =>
          /download|تحميل|تنزيل/i.test(x.text + ' ' + x.href)
        );

        const detailLinks = links.filter(x =>
          x.href &&
          !/download|تحميل|تنزيل/i.test(x.text + ' ' + x.href) &&
          !/javascript:|#/.test(x.href)
        );

        const icon = best.html.querySelector('img');

        output.push({
          name: title,
          description: best.text.slice(0, 2500),
          link: detailLinks.length ? detailLinks[0].href : '',
          icon: icon ? (icon.src || icon.getAttribute('data-src')) : null,
          downloads: downloadLinks.map(x => ({
            name: x.text || 'Download',
            link: x.href
          }))
        });
      }

      return output;
    }
    """) 


def add_game(games, item, category):
    name = (item.get("name") or "").strip()
    link = clean(item.get("link") or "")

    if not name or len(name) < 2:
        return

    if not link:
        print("No detail link:", name, flush=True)
        return

    if link in games:
        game = games[link]
    else:
        game = {
            "name": name,
            "link": link,
            "icon": item.get("icon"),
            "category": category,
            "description": item.get("description", ""),
            "downloads": []
        }
        games[link] = game

    if not game["icon"] and item.get("icon"):
        game["icon"] = absolute(item["icon"])

    for download in item.get("downloads", []):
        href = absolute(download.get("link"))

        if not href or href.startswith("javascript:"):
            continue

        if not any(x["link"] == href for x in game["downloads"]):
            game["downloads"].append({
                "name": download.get("name") or "Download",
                "link": href
            })


def get_detail_downloads(page):
    return page.locator("a[href]").evaluate_all("""
    els => els.map(a => ({
      name: (a.innerText || a.title ||
        a.getAttribute('aria-label') || '').trim(),
      link: a.href
    })).filter(x =>
      /download|تحميل|تنزيل|install/i.test(x.name + ' ' + x.link)
    )
    """)


def scroll_page(page):
    for _ in range(6):
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(700)


def main():
    games = {}
    categories = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )

        page = browser.new_page(
            viewport={"width": 1365, "height": 900}
        )
        page.set_default_timeout(20000)

        print("Opening website...", flush=True)

        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2500)

        categories.update(extract_categories(page))

        try:
            page.goto(
                BASE + "/en/categories",
                wait_until="domcontentloaded",
                timeout=45000
            )
            page.wait_for_timeout(2000)
            categories.update(extract_categories(page))
        except Exception as e:
            print("Category warning:", str(e)[:150], flush=True)

        print("Categories:", len(categories), flush=True)

        for category_url, category_name in categories.items():
            print("\nCATEGORY:", category_name, flush=True)

            previous_signature = None

            for page_number in range(1, 31):
                target = category_url

                if page_number > 1:
                    parsed = urlparse(target)
                    query = parse_qs(parsed.query)
                    query["page"] = [str(page_number)]
                    target = urlunparse(
                        parsed._replace(
                            query=urlencode(query, doseq=True)
                        )
                    )

                try:
                    response = page.goto(
                        target,
                        wait_until="domcontentloaded",
                        timeout=45000
                    )

                    if response and response.status >= 400:
                        print("HTTP:", response.status, flush=True)
                        break

                    page.wait_for_timeout(1500)
                    scroll_page(page)

                    cards = extract_cards(page, category_name)

                    signature = "|".join(
                        x.get("name", "") for x in cards
                    )

                    new_before = len(games)

                    for card in cards:
                        add_game(games, card, category_name)

                    new_games = len(games) - new_before

                    print(
                        "Page:", page_number,
                        "| Cards:", len(cards),
                        "| New:", new_games,
                        "| Total:", len(games),
                        flush=True
                    )

                    if not cards:
                        break

                    if signature == previous_signature:
                        print("Same page repeated; stopping.", flush=True)
                        break

                    previous_signature = signature

                except Exception as e:
                    print("Page error:", str(e)[:180], flush=True)
                    break

        # Visit game pages and collect additional download links.
        game_list = list(games.values())

        for number, game in enumerate(game_list, 1):
            print(
                f"DETAIL {number}/{len(game_list)}: {game['name']}",
                flush=True
            )

            try:
                page.goto(
                    game["link"],
                    wait_until="domcontentloaded",
                    timeout=45000
                )
                page.wait_for_timeout(1000)

                for item in get_detail_downloads(page):
                    href = absolute(item["link"])

                    if href and not any(
                        x["link"] == href for x in game["downloads"]
                    ):
                        game["downloads"].append({
                            "name": item["name"] or "Download",
                            "link": href
                        })

                if not game["icon"]:
                    game["icon"] = page.locator("img").evaluate_all("""
                    els => {
                      const x = els.find(i =>
                        i.src && i.naturalWidth > 80 &&
                        i.naturalHeight > 80
                      );
                      return x ? x.src : null;
                    }
                    """)

            except Exception as e:
                print("Detail warning:", str(e)[:150], flush=True)

        browser.close()

    final_games = list(games.values())

    result = {
        "source": URL,
        "count": len(final_games),
        "download_count": sum(
            len(x["downloads"]) for x in final_games
        ),
        "games": final_games
    }

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print("\n========================", flush=True)
    print("Games:", result["count"], flush=True)
    print("Downloads:", result["download_count"], flush=True)
    print("Saved:", OUT, flush=True)

    if not final_games:
        sys.exit("No game cards extracted. Check the website HTML.")


if __name__ == "__main__":
    main()
