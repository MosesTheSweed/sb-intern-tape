#!/usr/bin/env python3
from __future__ import annotations
import argparse, base64, json, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

CONTRACT = "0xfc4b0c4f464dc3037cf013934648a8a726d565a5"
RPC = "https://rpc.mainnet.chain.robinhood.com"
SUPPLY = 8888

def rpc(method, params):
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    raw = subprocess.check_output(["curl","-sS","-m","40","-X","POST",RPC,"-H","content-type: application/json","-d",payload])
    data = json.loads(raw)
    if "error" in data:
        raise RuntimeError(data["error"])
    return data["result"]

def decode_string(hexres: str) -> str:
    b = bytes.fromhex(hexres[2:])
    off = int.from_bytes(b[0:32], "big")
    ln = int.from_bytes(b[off:off+32], "big")
    return b[off+32:off+32+ln].decode()

def intern(tid: int) -> dict:
    uri = decode_string(rpc("eth_call", [{"to": CONTRACT, "data": f"0xc87b56dd{tid:064x}"}, "latest"]))
    meta = json.loads(base64.b64decode(uri.split(",", 1)[1]))
    attrs = {a["trait_type"]: a["value"] for a in meta.get("attributes") or []}
    owner = "0x" + rpc("eth_call", [{"to": CONTRACT, "data": f"0x6352211e{tid:064x}"}, "latest"])[-40:]
    share = str(attrs.get("Revenue Share") or "0%")
    try:
        pct = float(share.replace("%", ""))
    except ValueError:
        pct = 0.0
    return {
        "id": tid, "name": meta.get("name"), "class": attrs.get("Class"),
        "version": attrs.get("Intern Version"),
        "parent": int(str(attrs.get("Parent Broker") or "0") or 0),
        "title": attrs.get("Job Title"), "share": share, "sharePct": pct,
        "parentStatus": attrs.get("Parent Status"), "parentTier": attrs.get("Parent Broker Tier"),
        "status": attrs.get("Status"), "activation": attrs.get("Activation Tier"),
        "wallet": attrs.get("Wallet Address"), "badge": attrs.get("Broker Badge"),
        "owner": owner,
        "opensea": f"https://opensea.io/item/robinhood/{CONTRACT}/{tid}",
    }

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="interns.json")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--start", type=int, default=1)
    args = p.parse_args()
    end = SUPPLY if args.limit <= 0 else min(SUPPLY, args.start + args.limit - 1)
    ids = list(range(args.start, end + 1))
    rows, failed = {}, []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(intern, i): i for i in ids}
        done = 0
        for fut in as_completed(futs):
            i = futs[fut]
            done += 1
            try:
                rows[i] = fut.result()
            except Exception as e:
                failed.append(i)
                print(f"fail {i}: {e}", file=sys.stderr)
            if done % 50 == 0 or done == len(ids):
                print(f"{done}/{len(ids)} ok={len(rows)} fail={len(failed)}", file=sys.stderr)
    out = {
        "contract": CONTRACT,
        "updatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total": SUPPLY, "sampled": len(rows), "failed": failed,
        "interns": [rows[i] for i in sorted(rows)],
    }
    open(args.out, "w").write(json.dumps(out) + "\n")
    print(f"wrote {args.out} {len(rows)} in {time.time()-t0:.1f}s", file=sys.stderr)
    return 1 if failed else 0

if __name__ == "__main__":
    raise SystemExit(main())
