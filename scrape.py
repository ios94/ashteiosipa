name: Update Ashte JSON
on:
  workflow_dispatch:
  schedule:
    - cron: "0 */6 * * *"
permissions:
  contents: write
concurrency:
  group: ashte-scraper
  cancel-in-progress: true
jobs:
  scrape:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - name: Checkout Repository
        uses: actions/checkout@v4
      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install Dependencies
        run: |
          python -m pip install --upgrade pip
          pip install playwright
          playwright install --with-deps chromium
      - name: Run Scraper
        env:
          TARGET_URL: https://check0ver.net/en/iapps
        run: python scrape.py
      - name: Validate JSON
        run: |
          python -m json.tool ashte.json > /dev/null
          echo "JSON is valid"
      - name: Commit and Push
        run: |
          git config user.name "AshteMobile Bot"
          git config user.email "bot@users.noreply.github.com"
          git add ashte.json
          if git diff --cached --quiet; then
            echo "No changes to commit"
          else
            git commit -m "Update Ashte JSON"
            git push
          fi
