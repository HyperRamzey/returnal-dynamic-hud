import json
import os
from collections import Counter

import sqlite3

# --- Pi volume probe ---
pi_dir = os.path.expanduser(r"~\.pi\agent\sessions")
roles = Counter()
files = 0
for root, _, fns in os.walk(pi_dir):
    for fn in fns:
        if not fn.endswith(".jsonl"):
            continue
        files += 1
        try:
            with open(os.path.join(root, fn), encoding="utf-8") as fh:
                for line in fh:
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if rec.get("type") == "message":
                        roles[(rec.get("message") or {}).get("role", "?")] += 1
        except OSError:
            pass
print("PI files:", files, "roles:", roles.most_common())

# --- OpenCode volume probe (text parts joined to message role) ---
db = sqlite3.connect(
    r"file:C:\Users\admin\.local\share\opencode\opencode.db?mode=ro", uri=True
)
cur = db.cursor()
cur.execute(
    """SELECT m.data, p.data FROM part p
       JOIN message m ON m.id = p.message_id
       WHERE p.data LIKE '%"type": "text"%' OR p.data LIKE '%"type":"text"%'"""
)
rc = Counter()
chars = Counter()
for mdata, pdata in cur.fetchall():
    try:
        role = json.loads(mdata).get("role", "?")
        pd = json.loads(pdata)
    except json.JSONDecodeError:
        continue
    if pd.get("type") != "text":
        continue
    rc[role] += 1
    chars[role] += len(pd.get("text", "") or "")
print("OC text parts:", rc.most_common(), "chars:", dict(chars))
db.close()
