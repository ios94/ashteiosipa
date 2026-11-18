
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

GAME_CATEGORIES = {
    "games",
    "paid games",
    "arcade games",
    "العاب نيتندو سويتش",
}

def normalize(value):
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def get_page_data(page):
    """Read Inertia data embedded in the #app element."""
    try:
        raw = page.locator("#app").get_attribute("data-page")
        if raw:
            return json.loads(html.unescape(raw))
    except Exception:
        pass

    # Some Inertia responses may be JSON directly.
    try:
        body = page.locator("body").inner_text()
        return json.loads(body)
    except Exception:
        return {}


def find_categories(data):
    props = data.get("props", {})
    categories = props.get("categories", [])

    if not isinstance(categories, list):
        categories = []

    found = []

    for category in categories:
        name = category.get("name", "")
        if normalize(name) in GAME_CATEGORIES:
            found.append(category)

    # Also check categoriesWithApps.
    for category in props.get("categoriesWithApps", []):
        name = category.get("name", "")
        if normalize(name) in GAME_CATEGORIES:
            if not any(x.get("uuid") == category.get("uuid") for x in found):
                found.append(category)

    return found


def find_apps(value, output=None):
    """
    Recursively find app objects in Inertia props.
    App objects have uuid, name and image.
    """
    if output is None:
        output = {}

    if isinstance(value, dict):
        if (
            value.get("uuid")
            and value.get("name")
            and (
                value.get("image")
                or value.get("downloadURL") is not None
                or value.get("version")
            )
        ):
            output[value["uuid"]] = value

        for child in value.values():
            find_apps(child, output)

    elif isinstance(value, list):
        for child in value:
            find_apps(child, output)

    return output


def get_pagination(data):
    """Find pagination information, if supplied by the page."""
    props = data.get("props", {})

    def walk(value):
        if isinstance(value, dict):
            meta = value.get("meta")
            if isinstance(meta, dict):
                last = meta.get("last_page") or meta.get("lastPage")
                if last:
                    return int(last)

            last = value.get("last_page") or value.get("lastPage")
            if last:
                return int(last)

            for child in value.values():
                result = walk(child)
                if result:
                    return result

        elif isinstance(value, list):
            for child in value:
                result = walk(child)
                if result:
                    return result

        return None

    return walk(props)


def make_game(app, category):
    uuid = app.get("uuid")

    detail_url = f"{BASE}/en/iapps/{uuid}"
    download_url = f"{BASE}/api/iapps/{uuid}/download"

    image = app.get("image")
    if image and image.startswith("/"):
        image = BASE + image

    supplied_download = app.get("downloadURL")

    downloads = []

    if supplied_download:
        downloads.append({
            "name": "Original Download",
            "link": supplied_download
        })

    # Official CheckOver download endpoint.
    downloads.append({
        "name": "CheckOver Download",
        "link": download_url
    })

    return {
        "uuid": uuid,
        "name": app.get("name"),
        "link": detail_url,
        "icon": image,
        "description": app.get("description"),
        "version": app.get("version"),
        "size": app.get("size"),
        "bundle": app.get("bundle"),
        "downloads_count": app.get("downloads"),
        "category": category,
        "downloadURL": supplied_download,
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

        page.set_default_timeout(30000)

        print("Opening CheckOver...", flush=True)

        page.goto(
            URL,
            wait_until="domcontentloaded",
            timeout=60000
        )
        page.wait_for_timeout(2000)

        home_data = get_page_data(page)

        if not home_data:
            browser.close()
            sys.exit("Could not read CheckOver Inertia data.")

        categories_list = find_categories(home_data)

        print(
            "Game categories found:",
            len(categories_list),
            flush=True
        )

        for category in categories_list:
            name = category.get("name", "Games")
            uuid = category.get("uuid")

            if uuid:
                categories[uuid] = name

        if not categories:
            browser.close()
            sys.exit("No game categories found in homepage data.")

        for category_uuid, category_name in categories.items():
            print(
                "\nCategory:",
                category_name,
                "| UUID:",
                category_uuid,
                flush=True
            )

            last_page = 100
            previous_signature = None

            for page_number in range(1, last_page + 1):
                category_url = (
                    f"{BASE}/en/categories/{category_uuid}"
                    f"?page={page_number}"
                )

                try:
                    page.goto(
                        category_url,
                        wait_until="domcontentloaded",
                        timeout=45000
                    )
                    page.wait_for_timeout(1000)

                    data = get_page_data(page)

                    if not data:
                        print("No Inertia data; stopping category.", flush=True)
                        break

                    props = data.get("props", {})
                    apps = find_apps(props)

                    # The first page may have category apps in its own props.
                    signature = "|".join(sorted(apps.keys()))

                    new_count = 0

                    for app_uuid, app in apps.items():
                        if app_uuid not in games:
                            games[app_uuid] = make_game(
                                app,
                                category_name
                            )
                            new_count += 1

                    print(
                        "Page:", page_number,
                        "| Apps:", len(apps),
                        "| New:", new_count,
                        "| Total:", len(games),
                        flush=True
                    )

                    detected_last = get_pagination(data)
                    if detected_last:
                        last_page = min(detected_last, 100)

                    if not apps:
                        break

                    if signature == previous_signature:
                        print("Repeated page; stopping.", flush=True)
                        break

                    previous_signature = signature

                    if page_number >= last_page:
                        break

                except Exception as e:
                    print(
                        "Category page error:",
                        str(e)[:200],
                        flush=True
                    )
                    break

        browser.close()

    final_games = list(games.values())

    result = {
        "source": URL,
        "categories": list(categories.values()),
        "count": len(final_games),
        "download_count": sum(
            len(game["downloads"]) for game in final_games
        ),
        "games": final_games
    }

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print("\n==============================", flush=True)
    print("Total Games:", result["count"], flush=True)
    print("Download links:", result["download_count"], flush=True)
    print("Saved:", OUT, flush=True)

    if not final_games:
        sys.exit("No games were extracted.")


if __name__ == "__main__":
    main()
