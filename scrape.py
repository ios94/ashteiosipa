
import json
import os
import re
import sys
import html
from urllib.parse import urlencode
from playwright.sync_api import sync_playwright

BASE = "https://check0ver.net"
URL = os.getenv("TARGET_URL", BASE + "/en")
OUT = "ashte.json"

# These are category names, not game names.
GAME_CATEGORIES = {
    "games",
    "paid games",
    "arcade games",
    "العاب نيتندو سويتش",
}

MAX_PAGES_PER_CATEGORY = 400


def normalize(value):
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def get_inertia_data(page):
    try:
        raw = page.locator("#app").get_attribute("data-page")
        if raw:
            return json.loads(html.unescape(raw))
    except Exception:
        pass
    return {}


def get_categories(data):
    props = data.get("props", {})
    result = {}

    # The homepage contains categoriesWithApps and the first
    # batch of iapps for each category.
    for category in props.get("categoriesWithApps", []):
        name = category.get("name", "")
        uuid = category.get("uuid")

        if uuid and normalize(name) in GAME_CATEGORIES:
            result[uuid] = {
                "uuid": uuid,
                "name": name,
                "count": category.get("iappsCount", 0),
                "first_apps": category.get("iapps", [])
            }

    # Also include game categories listed in categories.
    for category in props.get("categories", []):
        name = category.get("name", "")
        uuid = category.get("uuid")

        if uuid and normalize(name) in GAME_CATEGORIES:
            if uuid not in result:
                result[uuid] = {
                    "uuid": uuid,
                    "name": name,
                    "count": category.get("iappsCount", 0),
                    "first_apps": []
                }

    return result


def is_app(item):
    if not isinstance(item, dict):
        return False

    # Do not mistake category records for actual games.
    return bool(
        item.get("uuid")
        and item.get("name")
        and (
            "uniqueBundle" in item
            or "bundle" in item
            or "version" in item
            or "size" in item
            or "downloadURL" in item
        )
    )


def collect_apps(value, output=None):
    if output is None:
        output = {}

    if isinstance(value, dict):
        if is_app(value):
            output[value["uuid"]] = value

        for child in value.values():
            collect_apps(child, output)

    elif isinstance(value, list):
        for child in value:
            collect_apps(child, output)

    return output


def find_last_page(value):
    if isinstance(value, dict):
        for key in ("last_page", "lastPage"):
            if value.get(key):
                try:
                    return int(value[key])
                except (ValueError, TypeError):
                    pass

        for child in value.values():
            found = find_last_page(child)
            if found:
                return found

    elif isinstance(value, list):
        for child in value:
            found = find_last_page(child)
            if found:
                return found

    return None


def category_url(uuid, page_number):
    query = {
        "filter[inCategories][0]": uuid,
        "page": page_number
    }
    return BASE + "/en/iapps?" + urlencode(query)


def official_download(uuid):
    return f"{BASE}/api/iapps/{uuid}/download"


def make_game(app, category):
    uuid = app["uuid"]
    image = app.get("image")

    downloads = []

    original = app.get("downloadURL")
    if original:
        downloads.append({
            "name": "Original Download",
            "link": original
        })

    # This is CheckOver's download endpoint, not a guarantee
    # that the file is public or that no login is required.
    downloads.append({
        "name": "CheckOver Download Endpoint",
        "link": official_download(uuid)
    })

    return {
        "uuid": uuid,
        "name": app.get("name"),
        "link": f"{BASE}/en/iapps/{uuid}",
        "icon": image,
        "description": app.get("description"),
        "version": app.get("version"),
        "size": app.get("size"),
        "bundle": app.get("bundle"),
        "uniqueBundle": app.get("uniqueBundle"),
        "downloads_count": app.get("downloads"),
        "views": app.get("views"),
        "isFree": app.get("isFree"),
        "hasAddonFiles": app.get("hasAddonFiles"),
        "category": category,
        "downloadURL": original,
        "downloads": downloads
    }


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
        page.set_default_timeout(25000)

        print("Opening CheckOver homepage...", flush=True)

        page.goto(
            URL,
            wait_until="domcontentloaded",
            timeout=60000
        )
        page.wait_for_timeout(1500)

        home_data = get_inertia_data(page)

        if not home_data:
            browser.close()
            sys.exit("ERROR: Could not read homepage Inertia data.")

        categories = get_categories(home_data)

        print("Game categories:", len(categories), flush=True)

        if not categories:
            browser.close()
            sys.exit("ERROR: No game categories found.")

        for category_uuid, category in categories.items():
            category_name = category["name"]
            expected_count = category["count"] or 0

            print(
                "\nCATEGORY:", category_name,
                "| Expected:", expected_count,
                flush=True
            )

            # First collect the actual app objects embedded
            # in categoriesWithApps on the homepage.
            first_apps = collect_apps(category["first_apps"])

            for app in first_apps.values():
                game = make_game(app, category_name)
                games[app["uuid"]] = game

            print(
                "Homepage apps:", len(first_apps),
                "| Total:", len(games),
                flush=True
            )

            # Read the remaining pages using the actual
            # category filter URL.
            last_page = None
            previous_signature = None

            for page_number in range(1, MAX_PAGES_PER_CATEGORY + 1):
                target = category_url(category_uuid, page_number)

                try:
                    response = page.goto(
                        target,
                        wait_until="domcontentloaded",
                        timeout=45000
                    )

                    if response and response.status >= 400:
                        print(
                            "HTTP error:",
                            response.status,
                            "| Page:", page_number,
                            flush=True
                        )
                        break

                    page.wait_for_timeout(500)

                    data = get_inertia_data(page)

                    if not data:
                        print(
                            "No Inertia data on page:",
                            page_number,
                            flush=True
                        )
                        break

                    apps = collect_apps(data.get("props", {}))

                    if not apps:
                        print(
                            "No apps on page:",
                            page_number,
                            flush=True
                        )
                        break

                    signature = "|".join(sorted(apps.keys()))

                    new_count = 0

                    for app in apps.values():
                        uuid = app["uuid"]

                        if uuid not in games:
                            games[uuid] = make_game(
                                app,
                                category_name
                            )
                            new_count += 1
                        else:
                            # Preserve all category memberships
                            # when a game appears in multiple lists.
                            old = games[uuid]
                            old_category = old["category"]

                            if category_name not in old_category.split(" | "):
                                old["category"] = (
                                    old_category + " | " + category_name
                                )

                    detected_last = find_last_page(data.get("props", {}))
                    if detected_last:
                        last_page = detected_last

                    print(
                        "Page:", page_number,
                        "| Apps:", len(apps),
                        "| New:", new_count,
                        "| Total:", len(games),
                        "| Last page:", last_page or "unknown",
                        flush=True
                    )

                    if signature == previous_signature:
                        print("Repeated page; stopping.", flush=True)
                        break

                    previous_signature = signature

                    if last_page and page_number >= last_page:
                        break

                except Exception as e:
                    print(
                        "Page error:",
                        page_number,
                        str(e)[:180],
                        flush=True
                    )
                    break

        browser.close()

    final_games = sorted(
        games.values(),
        key=lambda x: x["name"].lower()
    )

    result = {
        "source": URL,
        "categories": [
            {
                "name": item["name"],
                "uuid": item["uuid"],
                "expected_count": item["count"]
            }
            for item in categories.values()
        ],
        "count": len(final_games),
        "download_count": sum(
            len(game["downloads"]) for game in final_games
        ),
        "games": final_games
    }

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print("\n==============================", flush=True)
    print("Total games:", result["count"], flush=True)
    print("Download endpoints:", result["download_count"], flush=True)
    print("Saved:", OUT, flush=True)

    if not final_games:
        sys.exit("ERROR: No games were extracted.")


if __name__ == "__main__":
    main()
