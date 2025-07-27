import sqlite3
import json
import uuid
from typing import Optional, List
from datetime import datetime
from utils.data_models import Session, Message, TherapyPlan, UserProfile

class DatabaseService:
    """Service for handling all SQLite database operations."""
    
    def __init__(self, db_path: str):
        """
        Initialize the database service.
        
        Args:
            db_path (str): Path to the SQLite database file.
        """
        self.db_path = db_path
        self._initialize_database()
    
    def _initialize_database(self):
        """Create the necessary tables if they don't exist."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Create sessions table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                transcript TEXT NOT NULL
            )
        ''')
        
        # Create therapy_plans table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS therapy_plans (
                plan_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                plan_details TEXT NOT NULL,
                version INTEGER NOT NULL
            )
        ''')
        
        # Create user_profiles table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                birthdate TEXT,
                profession TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def _datetime_to_iso(self, dt: datetime) -> str:
        """Convert datetime to ISO format string."""
        return dt.isoformat()
    
    def _iso_to_datetime(self, iso_str: str) -> datetime:
        """Convert ISO format string to datetime."""
        return datetime.fromisoformat(iso_str)
    
    def save_session(self, session: Session) -> bool:
        """
        Save a session to the database.
        
        Args:
            session (Session): The session to save.
            
        Returns:
            bool: True if successful, False otherwise.
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Convert transcript to JSON string with proper datetime serialization
            transcript_data = []
            for msg in session.transcript:
                transcript_data.append({
                    "role": msg.role,
                    "content": msg.content,
                    "timestamp": self._datetime_to_iso(msg.timestamp)
                })
            
            transcript_json = json.dumps(transcript_data)
            
            cursor.execute('''
                INSERT INTO sessions (session_id, user_id, timestamp, transcript)
                VALUES (?, ?, ?, ?)
            ''', (
                session.session_id, 
                session.user_id, 
                self._datetime_to_iso(session.timestamp), 
                transcript_json
            ))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error saving session: {e}")
            return False
    
    def get_session(self, session_id: str) -> Optional[Session]:
        """
        Retrieve a session from the database.
        
        Args:
            session_id (str): The ID of the session to retrieve.
            
        Returns:
            Optional[Session]: The session if found, None otherwise.
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT session_id, user_id, timestamp, transcript
                FROM sessions
                WHERE session_id = ?
            ''', (session_id,))
            
            row = cursor.fetchone()
            conn.close()
            
            if row:
                # Parse transcript JSON
                transcript_data = json.loads(row[3])
                transcript = []
                for msg_data in transcript_data:
                    transcript.append(Message(
                        role=msg_data["role"],
                        content=msg_data["content"],
                        timestamp=self._iso_to_datetime(msg_data["timestamp"])
                    ))
                
                return Session(
                    session_id=row[0],
                    user_id=row[1],
                    timestamp=self._iso_to_datetime(row[2]),
                    transcript=transcript
                )
            return None
        except Exception as e:
            print(f"Error retrieving session: {e}")
            return None
    
    def save_therapy_plan(self, plan: TherapyPlan) -> bool:
        """
        Save a therapy plan to the database.
        
        Args:
            plan (TherapyPlan): The therapy plan to save.
            
        Returns:
            bool: True if successful, False otherwise.
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Convert plan_details to JSON string
            plan_details_json = json.dumps(plan.plan_details)
            
            cursor.execute('''
                INSERT INTO therapy_plans (plan_id, user_id, created_at, updated_at, plan_details, version)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                plan.plan_id,
                plan.user_id,
                self._datetime_to_iso(plan.created_at),
                self._datetime_to_iso(plan.updated_at),
                plan_details_json,
                plan.version
            ))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error saving therapy plan: {e}")
            return False
    
    def get_latest_therapy_plan(self, user_id: str = "default_user") -> Optional[TherapyPlan]:
        """
        Retrieve the latest therapy plan for a user.
        
        Args:
            user_id (str): The ID of the user.
            
        Returns:
            Optional[TherapyPlan]: The latest therapy plan if found, None otherwise.
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT plan_id, user_id, created_at, updated_at, plan_details, version
                FROM therapy_plans
                WHERE user_id = ?
                ORDER BY updated_at DESC
                LIMIT 1
            ''', (user_id,))
            
            row = cursor.fetchone()
            conn.close()
            
            if row:
                plan_details_data = json.loads(row[4])
                
                return TherapyPlan(
                    plan_id=row[0],
                    user_id=row[1],
                    created_at=self._iso_to_datetime(row[2]),
                    updated_at=self._iso_to_datetime(row[3]),
                    plan_details=plan_details_data,
                    version=row[5]
                )
            return None
        except Exception as e:
            print(f"Error retrieving therapy plan: {e}")
            return None
    
    def get_all_sessions_for_user(self, user_id: str = "default_user") -> List[Session]:
        """
        Retrieve all sessions for a user.
        
        Args:
            user_id (str): The ID of the user.
            
        Returns:
            List[Session]: List of all sessions for the user.
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT session_id, user_id, timestamp, transcript
                FROM sessions
                WHERE user_id = ?
                ORDER BY timestamp ASC
            ''', (user_id,))
            
            rows = cursor.fetchall()
            conn.close()
            
            sessions = []
            for row in rows:
                # Parse transcript JSON
                transcript_data = json.loads(row[3])
                transcript = []
                for msg_data in transcript_data:
                    transcript.append(Message(
                        role=msg_data["role"],
                        content=msg_data["content"],
                        timestamp=self._iso_to_datetime(msg_data["timestamp"])
                    ))
                
                sessions.append(Session(
                    session_id=row[0],
                    user_id=row[1],
                    timestamp=self._iso_to_datetime(row[2]),
                    transcript=transcript
                ))
            
            return sessions
        except Exception as e:
            print(f"Error retrieving sessions: {e}")
            return []
    
    def save_user_profile(self, profile: UserProfile) -> bool:
        """
        Save a user profile to the database.
        
        Args:
            profile (UserProfile): The user profile to save.
            
        Returns:
            bool: True if successful, False otherwise.
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR REPLACE INTO user_profiles 
                (user_id, name, birthdate, profession, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                profile.user_id,
                profile.name,
                self._datetime_to_iso(profile.birthdate) if profile.birthdate else None,
                profile.profession,
                self._datetime_to_iso(profile.created_at),
                self._datetime_to_iso(profile.updated_at)
            ))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error saving user profile: {e}")
            return False
    
    def get_user_profile(self, user_id: str) -> Optional[UserProfile]:
        """
        Retrieve a user profile from the database.
        
        Args:
            user_id (str): The ID of the user.
            
        Returns:
            Optional[UserProfile]: The user profile if found, None otherwise.
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT user_id, name, birthdate, profession, created_at, updated_at
                FROM user_profiles
                WHERE user_id = ?
            ''', (user_id,))
            
            row = cursor.fetchone()
            conn.close()
            
            if row:
                return UserProfile(
                    user_id=row[0],
                    name=row[1],
                    birthdate=self._iso_to_datetime(row[2]) if row[2] else None,
                    profession=row[3],
                    created_at=self._iso_to_datetime(row[4]),
                    updated_at=self._iso_to_datetime(row[5])
                )
            return None
        except Exception as e:
            print(f"Error retrieving user profile: {e}")
            return None
