#!/usr/bin/env python3
"""
Database Reset Script for Psychoanalyst App

This script resets all databases (SQLite and ChromaDB) to a clean state.
Includes a safety confirmation with a random math question.
"""

import os
import shutil
import random
import sys
from pathlib import Path

def get_random_math_question():
    """Generate a simple random math question and return question and answer."""
    operations = [
        (lambda a, b: (f"{a} + {b}", a + b)),
        (lambda a, b: (f"{a} - {b}", a - b)),
        (lambda a, b: (f"{a} * {b}", a * b)),
    ]
    
    # Generate two random numbers
    a = random.randint(1, 20)
    b = random.randint(1, 20)
    
    # For subtraction, ensure positive result
    if random.choice([True, False]) and a > b:
        operation = operations[1]  # subtraction
    elif random.choice([True, False]):
        operation = operations[0]  # addition
    else:
        operation = operations[2]  # multiplication
        # Keep multiplication small
        a = random.randint(1, 10)
        b = random.randint(1, 10)
    
    question, answer = operation(a, b)
    return question, answer

def reset_databases():
    """Reset all databases to clean state."""
    base_dir = Path(__file__).parent
    
    # Database paths
    vector_db_path = base_dir / "data" / "vector_db"
    main_db_path = base_dir / "data" / "psychoanalyst.db"
    test_db_path = base_dir / "data" / "psychoanalyst_test.db"
    
    print("Resetting databases...")
    
    # Remove ChromaDB vector database
    if vector_db_path.exists():
        print(f"Removing ChromaDB vector database: {vector_db_path}")
        shutil.rmtree(vector_db_path)
    else:
        print(f"ChromaDB vector database not found: {vector_db_path}")
    
    # Remove SQLite databases
    for db_path in [main_db_path, test_db_path]:
        if db_path.exists():
            print(f"Removing SQLite database: {db_path}")
            db_path.unlink()
        else:
            print(f"SQLite database not found: {db_path}")
    
    print("\n✅ All databases have been reset successfully!")
    print("The application will recreate them automatically on next run.")

def main():
    print("🚨 DATABASE RESET SCRIPT 🚨")
    print("This will permanently delete ALL databases and data!")
    print("- ChromaDB vector database (data/vector_db/)")
    print("- Production SQLite database (data/psychoanalyst.db)")
    print("- Test SQLite database (data/psychoanalyst_test.db)")
    print()
    
    # Safety confirmation with math question
    question, correct_answer = get_random_math_question()
    
    try:
        user_answer = input(f"To confirm, please solve: {question} = ")
        user_answer = int(user_answer.strip())
        
        if user_answer != correct_answer:
            print(f"❌ Incorrect answer. Expected {correct_answer}, got {user_answer}")
            print("Database reset cancelled for safety.")
            sys.exit(1)
        
        print("✅ Correct answer!")
        
    except (ValueError, KeyboardInterrupt):
        print("\n❌ Invalid input or cancelled by user.")
        print("Database reset cancelled for safety.")
        sys.exit(1)
    
    # Final confirmation
    confirm = input("\nAre you absolutely sure you want to reset all databases? (yes/no): ").strip().lower()
    
    if confirm != "yes":
        print("❌ Database reset cancelled.")
        sys.exit(1)
    
    # Perform the reset
    reset_databases()

if __name__ == "__main__":
    main()