import sqlite3
import hashlib
import time
import os
from typing import Optional, Dict, Any

DB_PATH = os.path.join(os.path.dirname(__file__), "voxlive.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    
    # 1. Users Table (NO RECORDINGS, NO TRANSCRIPTS, ZERO MEDIA STORAGE)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        phone TEXT UNIQUE NOT NULL,
        password_hash TEXT,
        balance_minutes REAL DEFAULT 15.0,
        plan_name TEXT DEFAULT 'Free Trial (15 Mins)',
        plan_expires_at REAL DEFAULT 0,
        created_at REAL NOT NULL
    )
    """)
    
    # 2. OTP Codes Table (Short-lived, auto expires in 5 minutes)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS otps (
        phone TEXT PRIMARY KEY,
        otp TEXT NOT NULL,
        expires_at REAL NOT NULL
    )
    """)
    
    # 3. Subscriptions / Orders Table (For income tracking)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS orders (
        order_id TEXT PRIMARY KEY,
        phone TEXT NOT NULL,
        plan_name TEXT NOT NULL,
        amount_inr REAL NOT NULL,
        payment_status TEXT NOT NULL,
        created_at REAL NOT NULL
    )
    """)
    
    conn.commit()
    conn.close()

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

def create_or_get_otp(phone: str) -> str:
    """Generates a 4-digit OTP valid for 5 minutes."""
    import random
    otp = f"{random.randint(1000, 9999)}"
    # For demo / testing convenience, '1234' is also accepted
    expires_at = time.time() + 300 # 5 minutes
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO otps (phone, otp, expires_at) VALUES (?, ?, ?)
    ON CONFLICT(phone) DO UPDATE SET otp=excluded.otp, expires_at=excluded.expires_at
    """, (phone, otp, expires_at))
    conn.commit()
    conn.close()
    return otp

def verify_otp(phone: str, user_otp: str) -> bool:
    """Verifies OTP (also accepts 1234 as universal test OTP)."""
    if user_otp == "1234":
        return True
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT otp, expires_at FROM otps WHERE phone = ?", (phone,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return False
    if time.time() > row["expires_at"]:
        return False
    return row["otp"] == user_otp

def get_or_create_user(phone: str) -> Dict[str, Any]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE phone = ?", (phone,))
    row = cursor.fetchone()
    
    if not row:
        now = time.time()
        cursor.execute("""
        INSERT INTO users (phone, balance_minutes, plan_name, created_at)
        VALUES (?, 15.0, 'Free Trial (15 Mins)', ?)
        """, (phone, now))
        conn.commit()
        cursor.execute("SELECT * FROM users WHERE phone = ?", (phone,))
        row = cursor.fetchone()
    
    user_dict = dict(row)
    conn.close()
    return user_dict

def set_user_password(phone: str, password: str):
    conn = get_db()
    cursor = conn.cursor()
    pwd_hash = hash_password(password)
    cursor.execute("UPDATE users SET password_hash = ? WHERE phone = ?", (pwd_hash, phone))
    conn.commit()
    conn.close()

def verify_password_login(phone: str, password: str) -> Optional[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    pwd_hash = hash_password(password)
    cursor.execute("SELECT * FROM users WHERE phone = ? AND password_hash = ?", (phone, pwd_hash))
    row = cursor.fetchone()
    conn.close()
    if row:
        return dict(row)
    return None

def deduct_user_time(phone: str, seconds_used: float) -> float:
    """Deducts used time in minutes from user balance (unless unlimited plan is active)."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT balance_minutes, plan_expires_at FROM users WHERE phone = ?", (phone,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return 0.0
    
    now = time.time()
    # If active unlimited plan, don't deduct
    if row["plan_expires_at"] and row["plan_expires_at"] > now:
        conn.close()
        return 999.0 # Unlimited
    
    mins_used = max(0.05, seconds_used / 60.0)
    new_balance = max(0.0, row["balance_minutes"] - mins_used)
    cursor.execute("UPDATE users SET balance_minutes = ? WHERE phone = ?", (new_balance, phone))
    conn.commit()
    conn.close()
    return new_balance

def activate_plan(phone: str, plan_id: str) -> Dict[str, Any]:
    """Activates commercial plan and records revenue/income."""
    plans = {
        "daily": {"name": "Daily Pass (24 Hours Unlimited)", "days": 1, "price": 29},
        "weekly": {"name": "Weekly Pass (7 Days Unlimited)", "days": 7, "price": 99},
        "monthly": {"name": "Monthly Pro (30 Days Unlimited)", "days": 30, "price": 249},
        "pack60": {"name": "60 Minutes Talk Pack", "mins": 60, "price": 49}
    }
    
    plan = plans.get(plan_id, plans["monthly"])
    now = time.time()
    order_id = f"ORD_{int(now)}_{phone[-4:]}"
    
    conn = get_db()
    cursor = conn.cursor()
    
    if "days" in plan:
        expires_at = now + (plan["days"] * 86400)
        cursor.execute("""
        UPDATE users SET plan_name = ?, plan_expires_at = ? WHERE phone = ?
        """, (plan["name"], expires_at, phone))
    else:
        cursor.execute("""
        UPDATE users SET balance_minutes = balance_minutes + ? WHERE phone = ?
        """, (plan["mins"], phone))
        
    cursor.execute("""
    INSERT INTO orders (order_id, phone, plan_name, amount_inr, payment_status, created_at)
    VALUES (?, ?, ?, ?, 'SUCCESS', ?)
    """, (order_id, phone, plan["name"], plan["price"], now))
    
    conn.commit()
    cursor.execute("SELECT * FROM users WHERE phone = ?", (phone,))
    user_row = dict(cursor.fetchone())
    conn.close()
    
    return {
        "order_id": order_id,
        "plan_name": plan["name"],
        "amount_paid": plan["price"],
        "user": user_row
    }

init_db()
