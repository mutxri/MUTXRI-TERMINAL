#!/usr/bin/env python3
"""sync_to_mongodb.py - push local terminal data files into MongoDB Atlas.
The hosted backend reads from Mongo instead of shipping large JSON files."""
import json, os, sys, urllib.parse
from pymongo import MongoClient

BASE = os.path.dirname(os.path.abspath(__file__))
PWD = "MONGO_PWD_ENV"
USER = "jimmymuturi99_db_user"
HOST = "terminaldatabase.5p16fjt.mongodb.net"
URI = f"mongodb+srv://{USER}:{urllib.parse.quote_plus(PWD)}@{HOST}/?appName=TERMINALDATABASE"

def load(name):
    p = os.path.join(BASE, name)
    if not os.path.exists(p):
        print(f"  MISSING {name}")
        return None
    return json.load(open(p, encoding="utf-8"))

def push_collection(db, coll_name, docs, key_field="_id"):
    if docs is None:
        return 0
    coll = db[coll_name]
    # upsert by _id to keep idempotent
    ops = []
    for i, d in enumerate(docs):
        if not isinstance(d, dict):
            continue
        doc = dict(d)
        oid = doc.get(key_field) or f"{coll_name}_{i}"
        doc["_id"] = str(oid)
        ops.append(doc)
    if ops:
        coll.delete_many({})
        coll.insert_many(ops)
    return len(ops)

client = MongoClient(URI, serverSelectionTimeoutMS=20000)
db = client["terminal"]
print("Connected to MongoDB Atlas:", db.client.list_database_names())

# 1. stocks.json -> collections per exchange + all
stocks = load("stocks.json")
if stocks and "stocks" in stocks:
    total = 0
    for ex in ["JSE", "EGX", "NGX", "NSE"]:
        n = push_collection(db, f"stocks_{ex}", stocks["stocks"].get(ex, []))
        print(f"  stocks_{ex}: {n}")
        total += n
    print(f"  total stocks: {total}")

# 2. fundamentals.json -> one doc per company
fund = load("fundamentals.json")
if fund:
    comps = fund.get("companies", {})
    coll = db["fundamentals"]
    coll.delete_many({})
    for key, val in comps.items():
        val = dict(val)
        val["_id"] = key
        coll.insert_one(val)
    print(f"  fundamentals: {len(comps)}")

# 3. ownership.json
own = load("ownership.json")
if own:
    n = push_collection(db, "ownership", [own])  # whole doc
    print(f"  ownership: stored")

# 4. filings_registry.json
fil = load("filings_registry.json")
if fil:
    coll = db["filings"]
    coll.delete_many({})
    coll.insert_one(fil)
    print(f"  filings: stored ({len(fil.get('filings', {}))} companies)")

# 5. af_slugs.json (AF ticker slugs)
slugs = load("af_slugs.json")
if slugs:
    n = push_collection(db, "af_slugs", [slugs])
    print(f"  af_slugs: stored")

print("\nSYNC COMPLETE")
client.close()
