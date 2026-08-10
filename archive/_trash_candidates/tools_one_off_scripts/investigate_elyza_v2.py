import sqlite3

print("--- SQLite Recent Jobs ---")
try:
    conn = sqlite3.connect('nazokake_local.db')
    cursor = conn.cursor()
    cursor.execute("SELECT doc_id, status, elyza_job_status, elyza_job_locked_at, llmjp_status FROM nazokake_items ORDER BY updated_at DESC LIMIT 5")
    rows = cursor.fetchall()
    if not rows:
        print("No records found.")
    else:
        for r in rows:
            print(r)
except Exception as e:
    print(e)
