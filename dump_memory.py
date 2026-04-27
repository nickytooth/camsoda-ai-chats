import sqlite3

DB = "data/bot.db"

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

# STM
rows = conn.execute(
    "SELECT role, content FROM messages ORDER BY id DESC LIMIT 20"
).fetchall()
print("=== RECENT STM (last 20) ===")
for r in reversed(rows):
    print(f"  [{r['role']}] {r['content'][:150]}")

# LTM
rows2 = conn.execute(
    "SELECT category, content, importance FROM memories ORDER BY importance DESC"
).fetchall()
print(f"\n=== LTM MEMORIES ({len(rows2)} total) ===")
for r in rows2:
    print(f"  [{r['category']}] imp={r['importance']}  {r['content'][:180]}")

conn.close()
