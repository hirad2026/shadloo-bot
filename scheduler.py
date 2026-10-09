from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime, timedelta
import aiosqlite
from aiogram import Bot

scheduler = AsyncIOScheduler()

async def send_hourly_reports(bot: Bot, admin_id: int):
    today = datetime.now().strftime("%Y-%m-%d")
    async with aiosqlite.connect("shadlou_bot.db") as db:
        cursor = await db.execute("SELECT id, task_name, responsible_username FROM tasks WHERE date = ?", (today,))
        tasks = await cursor.fetchall()
    
    for task in tasks:
        task_id, task_name, username = task
        # در نسخه کامل‌تر اینجا پیام به مسئول ارسال می‌شود
        # فعلاً ساده نگه داشتیم
        pass

def start_scheduler(bot: Bot, admin_id: int):
    # هر ساعت از ۸ تا ۱۷
    scheduler.add_job(send_hourly_reports, 'cron', hour='8-17', minute=0, args=[bot, admin_id])
    scheduler.start()