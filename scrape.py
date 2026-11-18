
import json
import os
import re
import sys
import time
from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse

from playwright.sync_api import sync_playwright

BASE = "https://check0ver.net"
URL = os.getenv("TARGET_URL", BASE + "/en")
OUT = "ashte.json"

GAME_CATEGORY_ID = "9c60f563-1983-42f0-8882-a26207bd4aaf"

GAME_WORDS = re.compile(
    r"game|games|gaming|paid games|arcade|nintendo|switch|"
    r"العاب|ألعاب|لعبة|ياري",
    re.I
)

DOWNLOAD_WORDS = re.compile(
    r"download|تحميل|تنزيل|install|direct|ipa|mediafire|"
    r"mega|drive\.google|file",
    re.I
)

SKIP_WORDS = re.compile(
    r"login|register|sign.?up|privacy|terms|contact|about|"
    r"telegram|facebook|instagram|pricing",
    re.I
)


def clean_url(url):
    if not url:
        return ""
    return url.split("#")[0].strip()


def absolute_url(url):
    return clean_url(urljoin(BASE, url))


def is_site_url(url):
    try:
        host = urlparse(url).netloc.lower()
        return host == "check0ver.net" or host.endswith(".check0ver.net")
    except Exception:
        return False


def unique(items):
    result = []
    seen = set()

    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)

    return result


def page_links(page):
    try:
        return page.locator("a[href]").evaluate_all("""
        els => els.map(a => ({
            text: (a.innerText || a.title ||
                   a.getAttribute('aria-label') || '').trim(),
            href: a.href,
            image: a.querySelector('img')?.src || null
        }))
        """)
    except Exception:
        return []


def get_categories(page):
    categories = {}

    for item in page_links(page):
        name = item.get("text", "").strip()
        link = clean_url(item.get("href", ""))

        if not name or not link or not is_site_url(link):
            continue

        if "/iapps" in link and GAME_WORDS.search(name):
            categories[link] = name

    # Known Games category
    categories[
        BASE + "/en/iapps?filter[inCategories][0]=" + GAME_CATEGORY_ID
    ] = "Games"

    return categories


def collect_cards(page, category_name):
    """
    Collect possible game detail links from the current listing page.
    Does not depend on a single card CSS class.
    """
    try:
        data = page.locator("a[href]").evaluate_all("""
        els => {
          const out = [];

          for (const a of els) {
            const href = a.href || "";
            const text = (a.innerText || a.title ||
              a.getAttribute('aria-label') || '').trim();

            if (!href.includes('/iapps')) continue;

            let node = a;
            let best = null;

            for (let i = 0; i < 7 && node; i++) {
              const cardText = (node.innerText || '').trim();

              if (cardText.length > 10 && cardText.length < 5000) {
                const img = node.querySelector('img');

                const links = [...node.querySelectorAll('a[href]')]
                  .map(x => ({
                    text: (x.innerText || x.title ||
                      x.getAttribute('aria-label') || '').trim(),
                    href: x.href
                  }));

                best = {
                  text: cardText,
                  image: img ? (img.src || img.getAttribute('data-src')) : null,
                  links: links
                };

                if (img || links.length > 1) break;
              }

              node = node.parentElement;
            }

            out.push({
              name: text,
              href: href,
              card: best
            });
          }

          return out;
        }
        """)

    except Exception as e:
        print("Card extraction error:", str(e)[:150], flush=True)
        return []

    results = []

    for item in data:
        href = clean_url(item.get("href", ""))

        if not href or not is_site_url(href):
            continue

        if SKIP_WORDS.search(href):
            continue

        card = item.get("card") or {}
        card_text = card.get("text") or ""
        name = item.get("name") or ""

        # Use card text to find a useful name when anchor is an image.
        if not name or len(name) < 2:
            lines = [
                x.strip()
                for x in card_text.splitlines()
                if x.strip()
            ]
            name = lines[0] if lines else ""

        if not name:
            continue

        if name.lower() in ("download", "view more", "read more"):
            continue

        results.append({
            "name": name[:180],
            "link": href,
            "icon": card.get("image"),
            "category": category_name,
            "card_links": card.get("links") or []
        })

    return results


def get_download_links(page):
    """
    Extract real links whose text, URL, or button attributes
    indicate a download action.
    """
    try:
        return page.locator(
            "a[href], button, [role='button']"
        ).evaluate_all("""
        els => els.map(el => {
          const text = (el.innerText || el.title ||
            el.getAttribute('aria-label') || '').trim();

          const href = el.href ||
            el.getAttribute('data-href') ||
            el.getAttribute('data-url') ||
            el.getAttribute('data-download') ||
            '';

          const onclick = el.getAttribute('onclick') || '';

          return {
            name: text,
            link: href,
            onclick: onclick,
            html: el.outerHTML.slice(0, 1500)
          };
        })
        """)
    except Exception:
        return []


def extract_downloads(page):
    found = []

    for item in get_download_links(page):
        name = item.get("name", "")
        link = item.get("link", "")
        onclick = item.get("onclick", "")
        html = item.get("html", "")

        combined = " ".join([name, link, onclick, html])

        if not DOWNLOAD_WORDS.search(combined):
            continue

        # Ignore buttons without an actual destination.
        if not link:
            match = re.search(
                r"""(?:https?://[^"'\\s<>]+|/[^"'\\s<>]+)""",
                onclick
            )
            if match:
                link = match.group(0)

        if not link:
            continue

        link = absolute_url(link)

        if link.startswith("javascript:") or link.startswith("mailto:"):
            continue

        found.append({
            "name": name or "Download",
            "link": link
        })

    unique_found = []
    seen = set()

    for item in found:
        if item["link"] not in seen:
            seen.add(item["link"])
            unique_found.append(item)

    return unique_found


def get_icon(page):
    try:
        return page.locator("img").evaluate_all("""
        els => {
          const img = els.find(x =>
            x.src &&
            x.naturalWidth >= 60 &&
            x.naturalHeight >= 60
          );
          return img ? img.src : null;
        }
        """)
    except Exception:
        return None


def scroll_listing(page):
    """
    Trigger lazy-loaded cards and infinite scrolling.
    """
    previous = -1

    for _ in range(7):
        try:
            count = page.locator("a[href*='/iapps']").count()

            if count == previous:
                page.evaluate(
                    "window.scrollTo(0, document.body.scrollHeight)"
                )
                page.wait_for_timeout(900)
            else:
                previous = count
                page.evaluate(
                    "window.scrollTo(0, document.body.scrollHeight)"
                )
                page.wait_for_timeout(1200)

        except Exception:
            break


def add_game(games, item):
    link = clean_url(item.get("link", ""))

    if not link:
        return

    if link not in games:
        games[link] = {
            "name": item.get("name") or "Unknown",
            "link": link,
            "icon": item.get("icon"),
            "category": item.get("category", ""),
            "downloads": []
        }

    game = games[link]

    if not game["icon"] and item.get("icon"):
        game["icon"] = item["icon"]

    if item.get("card_links"):
        for candidate in item["card_links"]:
            text = candidate.get("text", "")
            href = candidate.get("href", "")

            if DOWNLOAD_WORDS.search(text + " " + href) and href:
                href = absolute_url(href)

                if not any(x["link"] == href for x in game["downloads"]):
                    game["downloads"].append({
                        "name": text or "Download",
                        "link": href
                    })


def main():
    games = {}
    categories = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )

        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1365, "height": 900}
        )

        page = context.new_page()
        page.set_default_timeout(20000)

        print("Opening website...", flush=True)

        try:
            page.goto(
                URL,
                wait_until="domcontentloaded",
                timeout=60000
            )
            page.wait_for_timeout(3000)

            # Find categories on homepage.
            categories.update(get_categories(page))

            # Also inspect category page.
            try:
                page.goto(
                    BASE + "/en/categories",
                    wait_until="domcontentloaded",
                    timeout=45000
                )
                page.wait_for_timeout(2000)
                categories.update(get_categories(page))
            except Exception as e:
                print("Category page warning:", str(e)[:150], flush=True)

            print("Found categories:", len(categories), flush=True)

            # Scan each game category.
            for category_url, category_name in categories.items():
                print(
                    "\nCategory:", category_name,
                    flush=True
                )

                visited_page_counts = set()

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
                            print(
                                "HTTP status:",
                                response.status,
                                flush=True
                            )
                            break

                        page.wait_for_timeout(1200)
                        scroll_listing(page)

                        cards = collect_cards(page, category_name)

                        new_count = 0

                        for card in cards:
                            before = len(games)
                            add_game(games, card)

                            if len(games) > before:
                                new_count += 1

                        print(
                            "Page:", page_number,
                            "| Cards:", len(cards),
                            "| New:", new_count,
                            "| Total:", len(games),
                            flush=True
                        )

                        current_count = len(games)

                        if page_number > 1 and current_count in visited_page_counts:
                            break

                        visited_page_counts.add(current_count)

                        if not cards:
                            break

                    except Exception as e:
                        print(
                            "Listing error:",
                            str(e)[:180],
                            flush=True
                        )
                        break

            # Visit each game detail page.
            game_list = list(games.values())

            for number, game in enumerate(game_list, 1):
                print(
                    f"Details {number}/{len(game_list)}: {game['name']}",
                    flush=True
                )

                try:
                    page.goto(
                        game["link"],
                        wait_until="domcontentloaded",
                        timeout=45000
                    )
                    page.wait_for_timeout(1200)

                    downloads = extract_downloads(page)

                    for download in downloads:
                        if not any(
                            x["link"] == download["link"]
                            for x in game["downloads"]
                        ):
                            game["downloads"].append(download)

                    if not game["icon"]:
                        game["icon"] = get_icon(page)

                    # Use page title if card name was only a placeholder.
                    if game["name"] == "Unknown":
                        title = page.title().strip()
                        if title:
                            game["name"] = title[:180]

                except Exception as e:
                    print(
                        "Detail warning:",
                        str(e)[:150],
                        flush=True
                    )

            browser.close()

        except Exception as e:
            print("Fatal scraper error:", repr(e), flush=True)
            try:
                browser.close()
            except Exception:
                pass
            raise

    # Remove duplicate games and empty names.
    final_games = []

    for game in games.values():
        if not game["name"] or not game["link"]:
            continue

        final_games.append(game)

    result = {
        "source": URL,
        "count": len(final_games),
        "download_count": sum(
            len(game["downloads"]) for game in final_games
        ),
        "games": final_games
    }

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print("\n==========================", flush=True)
    print("Games:", result["count"], flush=True)
    print("Downloads:", result["download_count"], flush=True)
    print("Saved:", OUT, flush=True)

    if not final_games:
        print(
            "WARNING: No game cards were extracted. "
            "Check debug logs and website structure.",
            flush=True
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
