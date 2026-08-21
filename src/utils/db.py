import os
import sqlite3
import secrets
import hashlib
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# Resolve project directories
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DB_DIR = os.path.join(PROJECT_ROOT, "config")
DB_PATH = os.path.join(DB_DIR, "app.db")

def get_db_connection() -> sqlite3.Connection:
    """Acquires a sqlite3 database connection with dictionary-like row formatting."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def hash_password(password: str) -> str:
    """Hashes a password using PBKDF2-HMAC-SHA256 with 100,000 iterations and a unique salt."""
    salt = secrets.token_hex(16)
    pwd_hash = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        100000
    ).hex()
    return f"{salt}:{pwd_hash}"

def verify_password(password: str, hashed_str: str) -> bool:
    """Verifies a plain password against a stored hashed salt:hash combination."""
    try:
        salt, pwd_hash = hashed_str.split(":")
        calculated_hash = hashlib.pbkdf2_hmac(
            'sha256',
            password.encode('utf-8'),
            salt.encode('utf-8'),
            100000
        ).hex()
        return calculated_hash == pwd_hash
    except Exception:
        return False

def init_db():
    """Initializes SQLite database tables and seeds the default administrator if empty."""
    os.makedirs(DB_DIR, exist_ok=True)
    logger.info("Initializing SQLite database at %s", DB_PATH)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Create Users Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # 2. Create Sessions Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            FOREIGN KEY (username) REFERENCES users(username) ON DELETE CASCADE
        )
    """)
    
    # 3. Create Audit Logs Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            username TEXT NOT NULL,
            action TEXT NOT NULL,
            details TEXT,
            ip_address TEXT
        )
    """)
    
    conn.commit()
    
    # Seed default user if no user exists
    cursor.execute("SELECT COUNT(*) FROM users")
    count = cursor.fetchone()[0]
    if count == 0:
        logger.info("No users registered. Seeding default administrator account.")
        admin_pass_hash = hash_password("admin")
        cursor.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
            ("admin", admin_pass_hash, "admin")
        )
        conn.commit()
        
    conn.close()

# --- USER CRUD ACTIONS ---

def create_user(username: str, password_plain: str, role: str) -> bool:
    """Registers a new user into the database."""
    conn = get_db_connection()
    cursor = conn.cursor()
    pwd_hash = hash_password(password_plain)
    try:
        cursor.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
            (username.strip(), pwd_hash, role.strip().lower())
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        logger.warning("User registration failed: User %s already exists.", username)
        return False
    finally:
        conn.close()

def delete_user(username: str) -> bool:
    """Deletes a user by username."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM users WHERE username = ?", (username.strip(),))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()

def update_user_password(username: str, new_password_plain: str) -> bool:
    """Updates a user's password_hash in the database."""
    conn = get_db_connection()
    cursor = conn.cursor()
    pwd_hash = hash_password(new_password_plain)
    try:
        cursor.execute(
            "UPDATE users SET password_hash = ? WHERE username = ?",
            (pwd_hash, username.strip())
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()

def get_user(username: str) -> Optional[Dict[str, Any]]:
    """Retrieves user row by username."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT username, password_hash, role, created_at FROM users WHERE username = ?", (username.strip(),))
    row = cursor.fetchone()
    conn.close()
    if row:
        return dict(row)
    return None

def list_users() -> List[Dict[str, Any]]:
    """Lists all users registered in the system."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT username, role, created_at FROM users ORDER BY username ASC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

# --- SESSIONS ACTIONS ---

def create_session(username: str, lifespan_hours: int = 24) -> str:
    """Generates a new session token, persists it to the sessions table, and returns it."""
    session_id = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(hours=lifespan_hours)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO sessions (session_id, username, expires_at) VALUES (?, ?, ?)",
        (session_id, username, expires_at.isoformat())
    )
    conn.commit()
    conn.close()
    return session_id

def get_session_user(session_id: str) -> Optional[Dict[str, Any]]:
    """Validates session token and returns active user model if session is valid/active."""
    # First clean up stale sessions
    cleanup_expired_sessions()
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Query matching session and user
    cursor.execute("""
        SELECT u.username, u.role 
        FROM sessions s
        JOIN users u ON s.username = u.username
        WHERE s.session_id = ? AND s.expires_at > ?
    """, (session_id, datetime.utcnow().isoformat()))
    
    row = cursor.fetchone()
    conn.close()
    if row:
        return dict(row)
    return None

def delete_session(session_id: str):
    """Revokes / deletes a session by token."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
    conn.commit()
    conn.close()

def cleanup_expired_sessions():
    """Prunes expired sessions from the database."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM sessions WHERE expires_at < ?", (datetime.utcnow().isoformat(),))
    conn.commit()
    conn.close()

# --- AUDIT LOGS ACTIONS ---

def log_action(username: str, action: str, details: Optional[str] = None, ip_address: Optional[str] = None):
    """Registers a user action to the audit logs table."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO audit_logs (username, action, details, ip_address) VALUES (?, ?, ?, ?)",
        (username, action, details, ip_address)
    )
    conn.commit()
    conn.close()

def get_audit_logs(start_date: Optional[str] = None, end_date: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieves audit logs filtered by start_date and end_date ranges."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = "SELECT id, timestamp, username, action, details, ip_address FROM audit_logs WHERE 1=1"
    params = []
    
    if start_date:
        # start_date is YYYY-MM-DD
        query += " AND timestamp >= ?"
        params.append(f"{start_date} 00:00:00")
    if end_date:
        query += " AND timestamp <= ?"
        params.append(f"{end_date} 23:59:59")
        
    query += " ORDER BY timestamp DESC"
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]
