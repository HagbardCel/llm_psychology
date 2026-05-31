#!/usr/bin/env python3
"""
Script to check the actual contents of the psychoanalyst database after a real session.
"""

import json
import sqlite3


def check_database(db_path):
    """Check the contents of the database tables."""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        print("=== Database Contents After Real Session ===\n")

        # Check sessions table
        print("Sessions table:")
        cursor.execute("SELECT COUNT(*) FROM sessions")
        count = cursor.fetchone()[0]
        print(f"  Total sessions: {count}")

        if count > 0:
            cursor.execute(
                "SELECT session_id, user_id, timestamp, transcript FROM sessions"
            )
            rows = cursor.fetchall()
            for i, row in enumerate(rows):
                print(f"  Session {i + 1}:")
                print(f"    - Session ID: {row[0]}")
                print(f"    - User ID: {row[1]}")
                print(f"    - Timestamp: {row[2]}")
                # Show first few characters of transcript
                transcript_preview = (
                    row[3][:100] + "..." if len(row[3]) > 100 else row[3]
                )
                print(f"    - Transcript preview: {transcript_preview}")
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
                "SELECT plan_id, user_id, created_at, updated_at, plan_details, version FROM therapy_plans"
            )
            rows = cursor.fetchall()
            for i, row in enumerate(rows):
                print(f"  Plan {i + 1}:")
                print(f"    - Plan ID: {row[0]}")
                print(f"    - User ID: {row[1]}")
                print(f"    - Created: {row[2]}")
                print(f"    - Updated: {row[3]}")
                print(f"    - Version: {row[5]}")
                # Show plan details preview
                plan_details = json.loads(row[4])
                print(f"    - Plan focus: {plan_details.get('focus', 'N/A')[:100]}...")
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
                "SELECT user_id, name, date_of_birth, profession, created_at FROM user_profiles"
            )
            rows = cursor.fetchall()
            for i, row in enumerate(rows):
                print(f"  Profile {i + 1}:")
                print(f"    - User ID: {row[0]}")
                print(f"    - Name: {row[1]}")
                print(f"    - Birthdate: {row[2]}")
                print(f"    - Profession: {row[3]}")
                print(f"    - Created: {row[4]}")
        else:
            print("  No user profiles found")

        conn.close()

    except Exception as e:
        print(f"Error checking database: {e}")


if __name__ == "__main__":
    db_path = "data/psychoanalyst.db"
    check_database(db_path)
