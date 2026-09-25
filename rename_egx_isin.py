import json, os
stocks = json.load(open("stocks.json", encoding="utf-8"))["stocks"]["EGX"]
HIST = "static_data/history"
renamed = renamed_max = 0
for s in stocks:
    ticker = s.get("ticker")
    sym = s.get("sym")
    if not ticker or not sym:
        continue
    src = f"{HIST}/{ticker}.CA.json"
    dst = f"{HIST}/{sym}.json"
    src_max = f"{HIST}/{ticker}.CA.max.json"
    dst_max = f"{HIST}/{sym}.max.json"
    if os.path.exists(src):
        os.replace(src, dst)  # deep TV data overwrites old shallow ISIN file
        renamed += 1
    if os.path.exists(src_max):
        os.replace(src_max, dst_max)
        renamed_max += 1
print(f"renamed {renamed} daily + {renamed_max} monthly EGX files to ISIN naming")
