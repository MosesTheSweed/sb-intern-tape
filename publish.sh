#!/bin/sh
set -e
cd /home/holmes/sb-intern-tape
python3 crawl_interns.py --out interns.json --workers 3
python3 crawl_listings.py --json interns.json
git add interns.json
git diff --cached --quiet && exit 0
git commit -m "intern snapshot $(date -u +%Y-%m-%dT%H:%MZ)"
git push
