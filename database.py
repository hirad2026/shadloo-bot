import aiosqlite
from datetime import datetime

DB_NAME = "shadlou_bot.db"

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL,
                username TEXT UNIQUE NOT NULL,
                telegram_id INTEGER
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                time TEXT NOT NULL,
                task_name TEXT NOT NULL,
                responsible_username TEXT NOT NULL,
                planned_percent INTEGER DEFAULT 0,
                resources TEXT,
                status TEXT DEFAULT 'در انتظار',
                actual_percent INTEGER DEFAULT 0,
                reason TEXT,
                last_report TEXT
            )
        """)
        await db.commit()

async def add_user(full_name: str, username: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (full_name, username) VALUES (?, ?)",
            (full_name, username.lower().replace("@", ""))
        )
        await db.commit()

async def get_all_users():
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT full_name, username FROM users")
        return await cursor.fetchall()

async def add_task(date: str, time: str, task_name: str, responsible_username: str, planned_percent: int, resources: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            INSERT INTO tasks (date, time, task_name, responsible_username, planned_percent, resources)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (date, time, task_name, responsible_username.lower().replace("@", ""), planned_percent, resources))
        await db.commit()

async def get_tasks_by_date(date: str):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT * FROM tasks WHERE date = ?", (date,))
        return await cursor.fetchall()

async def update_task_status(task_id: int, status: str, actual_percent: int = 0, reason: str = None):
    async with aiosqlite.connect(DB_NAME) as db:
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        await db.execute("""
            UPDATE tasks 
            SET status = ?, actual_percent = ?, reason = ?, last_report = ?
            WHERE id = ?
        """, (status, actual_percent, reason, now, task_id))
        await db.commit()