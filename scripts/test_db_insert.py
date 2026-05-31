import json
import sqlite3
from datetime import datetime

db_path = "data/psychoanalyst_usertest.db"
user_id = "console_user_test"
intake_session_id = "f4dae00e-e00e-4df1-87fb-af68c1ea6497"
recommendations = [{"style_id": "test", "score": 1.0}]
payload = json.dumps(recommendations)
created_at = datetime.now().isoformat()

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

print(f"Attempting to insert into {db_path}...")
try:
    cursor.execute(
        """
        INSERT OR REPLACE INTO assessment_recommendations
        (user_id, intake_session_id, recommendations, created_at)
        VALUES (?, ?, ?, ?)
    """,
        (user_id, intake_session_id, payload, created_at),
    )
    conn.commit()
    print("Insert successful.")
except Exception as e:
    print(f"Insert failed: {e}")

# Verify
cursor.execute("SELECT * FROM assessment_recommendations WHERE user_id = ?", (user_id,))
rows = cursor.fetchall()
print(f"Rows found: {rows}")

conn.close()
