
import sqlite3
import urllib.request

print("--- SQLite Recent Jobs ---")
try:
    conn = sqlite3.connect('nazokake_local.db')
    cursor = conn.cursor()
    cursor.execute("SELECT doc_id, elyza_status, eval_status FROM NazokakeItem ORDER BY doc_id DESC LIMIT 5")
    for r in cursor.fetchall(): print(r)
except Exception as e:
    print(e)

print("--- Ollama Status ---")
try:
    urllib.request.urlopen("http://127.0.0.1:11434/")
    print("Ollama is running.")
except Exception as e:
    print("Ollama unreachable:", e)
