
import sqlite3
import pandas as pd
import os

db_path = 'data/psychoanalyst_usertest.db'

if not os.path.exists(db_path):
    print(f"Database not found at {db_path}")
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# List tables
cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
tables = cursor.fetchall()
print("Tables found:", [t[0] for t in tables])

# Check content of likely tables
likely_tables = ['assessment_recommendations', 'assessments', 'recommendations', 'therapy_plans']
found_relevant = False

for table_name in [t[0] for t in tables]:
    if any(likely in table_name for likely in likely_tables) or 'assessment' in table_name:
        print(f"\n--- Content of table: {table_name} ---")
        try:
            df = pd.read_sql_query(f"SELECT * FROM {table_name}", conn)
            print(df.to_string())
            found_relevant = True
        except Exception as e:
            print(f"Error reading {table_name}: {e}")

conn.close()
