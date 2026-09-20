#!/usr/bin/env python3
"""Merge OpenSea listings/offers/floor into interns.json.

Key file (not in git): ~/.config/intern-tape/opensea.key
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

CONTRACT = "0xfc4b0c4f464dc3037cf013934648a8a726d565a5"
CHAIN = "robinhood"
KEY_PATH = os.path.expanduser("~/.config/intern-tape/opensea.key")
API = "https://api.opensea.io/api/v2"


def key() -> str:
    k = open(KEY_PATH).read().strip().strip("'\"")
    if not k:
        raise SystemExit(f"empty key at {KEY_PATH}")
    return k


def get(path: str, params: str = "", tries: int = 6) -> dict:
    url = f"{API}{path}"
    if params:
        url += ("&" if "?" in path else "?") + params
    delay = 2.0
    last = None
    for _ in range(tries):
        raw = subprocess.check_output(
            [
                "curl",
                "-sS",
                "-m",
                "40",
                "-w",
                "\n%{http_code}",
                "-H",
                f"X-API-KEY: {key()}",
                "-H",
                "accept: application/json",
                url,
            ]
        )
        body, _, code = raw.decode().rpartition("\n")
        code = code.strip()
        if code == "200":
            return json.loads(body or "{}")
        last = (code, body[:400])
        if code in ("429", "503"):
            time.sleep(delay)
            delay = min(delay * 2, 30)
            continue
        raise RuntimeError(f"GET {path} -> {code} {body[:300]}")
    raise RuntimeError(f"GET {path} failed {last}")


def wei_to_eth(value, decimals=18) -> float | None:
    try:
        return int(value) / (10 ** int(decimals))
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def price_eth(obj: dict | None) -> float | None:
    if not obj:
        return None
    cur = obj.get("current") or obj.get("value") or obj
    if isinstance(cur, dict):
        return wei_to_eth(cur.get("value") or cur.get("raw"), cur.get("decimals") or 18)
    return None


def token_id_from_listing(item: dict) -> int | None:
    for path in (
        ["nft", "identifier"],
        ["criteria", "token", "identifier"],
        ["protocol_data", "parameters", "offer", 0, "identifierOrCriteria"],
    ):
        cur: object = item
        ok = True
        for p in path:
            if isinstance(p, int) and isinstance(cur, list) and len(cur) > p:
                cur = cur[p]
            elif isinstance(p, str) and isinstance(cur, dict):
                cur = cur.get(p)
            else:
                ok = False
                break
        if ok and cur not in (None, ""):
            try:
                return int(str(cur))
            except ValueError:
                pass
    return None


def paginate(path: str, list_key: str) -> list:
    out, next_cur = [], None
    while True:
        params = "limit=100"
        if next_cur:
            params += f"&next={next_cur}"
        data = get(path, params)
        chunk = data.get(list_key) or data.get("orders") or []
        out.extend(chunk)
        next_cur = data.get("next")
        print(f"  {path} +{len(chunk)} total={len(out)}", file=sys.stderr)
        if not next_cur or not chunk:
            break
        time.sleep(0.25)
    return out


def slug_for_contract() -> str:
    nft = get(f"/chain/{CHAIN}/contract/{CONTRACT}/nfts/85")
    col = (nft.get("nft") or nft).get("collection") or ""
    if isinstance(col, dict):
        col = col.get("collection") or col.get("slug") or ""
    if not col:
        raise RuntimeError(f"no collection slug in {list(nft)[:8]}")
    return str(col)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--json", default="interns.json")
    args = p.parse_args()
    dump = json.load(open(args.json))
    slug = slug_for_contract()
    print(f"collection slug={slug}", file=sys.stderr)

    stats = get(f"/collections/{slug}/stats")
    floor = None
    total = stats.get("total") or stats
    floor_raw = (
        (total.get("floor_price") if isinstance(total, dict) else None)
        or stats.get("floor_price")
        or {}
    )
    if isinstance(floor_raw, dict):
        floor = floor_raw.get("value") or floor_raw.get("eth") or floor_raw.get("floor")
        if isinstance(floor, str):
            try:
                floor = float(floor)
            except ValueError:
                floor = wei_to_eth(floor)
    elif isinstance(floor_raw, (int, float)):
        floor = float(floor_raw)
    print(f"floor={floor}", file=sys.stderr)

    listings = paginate(f"/listings/collection/{slug}/all", "listings")
    try:
        offers = paginate(f"/offers/collection/{slug}/all", "offers")
    except Exception as e:
        print(f"offers skip: {e}", file=sys.stderr)
        offers = []

    ask: dict[int, float] = {}
    bid: dict[int, float] = {}
    for item in listings:
        tid = token_id_from_listing(item)
        px = price_eth(item.get("price"))
        if tid is None or px is None:
            continue
        ask[tid] = min(px, ask[tid]) if tid in ask else px
    for item in offers:
        tid = token_id_from_listing(item)
        px = price_eth(item.get("price"))
        if tid is None or px is None:
            continue
        bid[tid] = max(px, bid[tid]) if tid in bid else px

    for row in dump["interns"]:
        tid = int(row["id"])
        a, b = ask.get(tid), bid.get(tid)
        row["listed"] = a is not None
        row["askEth"] = a
        row["offerEth"] = b
        row["vsFloor"] = (a / floor) if a and floor else None

    dump["floorEth"] = floor
    dump["osSlug"] = slug
    dump["osUpdatedAt"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    dump["listedCount"] = len(ask)
    open(args.json, "w").write(json.dumps(dump) + "\n")
    print(
        f"merged listed={len(ask)} bids={len(bid)} floor={floor} -> {args.json}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
