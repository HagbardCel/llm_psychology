#!/usr/bin/env python3
"""
Script to check the contents of the psychoanalyst database.
"""

import sqlite3


def check_database(db_path):
    """Check the contents of the database tables."""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        print("=== Database Contents ===\n")

        # Check sessions table
        print("Sessions table:")
        cursor.execute("SELECT COUNT(*) FROM sessions")
        count = cursor.fetchone()[0]
        print(f"  Total sessions: {count}")

        if count > 0:
            cursor.execute(
                "SELECT session_id, user_id, timestamp FROM sessions LIMIT 5"
            )
            rows = cursor.fetchall()
            for row in rows:
                print(
                    f"  - Session ID: {row[0]}, User ID: {row[1]}, Timestamp: {row[2]}"
                )
        else:
            print("  No sessions found")

        print()

        # Check therapy_plans table
        print("Therapy Plans table:")
        cursor.execute("SELECT COUNT(*) FROM therapy_plans")
        count = cursor.fetchone()[0]
        print(f"  Total therapy plans: {count}")

        if count > 0:
            cursor.execute(
                "SELECT plan_id, user_id, created_at, version FROM therapy_plans LIMIT 5"
            )
            rows = cursor.fetchall()
            for row in rows:
                print(
                    f"  - Plan ID: {row[0]}, User ID: {row[1]}, Created: {row[2]}, Version: {row[3]}"
                )
        else:
            print("  No therapy plans found")

        print()

        # Check user_profiles table
        print("User Profiles table:")
        cursor.execute("SELECT COUNT(*) FROM user_profiles")
        count = cursor.fetchone()[0]
        print(f"  Total user profiles: {count}")

        if count > 0:
            cursor.execute(
                "SELECT user_id, name, created_at FROM user_profiles LIMIT 5"
            )
            rows = cursor.fetchall()
            for row in rows:
                print(f"  - User ID: {row[0]}, Name: {row[1]}, Created: {row[2]}")
        else:
            print("  No user profiles found")

        conn.close()

    except Exception as e:
        print(f"Error checking database: {e}")


if __name__ == "__main__":
    db_path = "data/psychoanalyst.db"
    check_database(db_path)
