import asyncio
import logging
import re
import aiosqlite
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.storage.memory import MemoryStorage
import os

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID"))
IRAN_TZ = ZoneInfo("Asia/Tehran")

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
logging.basicConfig(level=logging.INFO)

DB_NAME = "/data/shadloo_bot.db"

def now_iran():
    return datetime.now(IRAN_TZ)

# ==================== دیتابیس ====================
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT,
                username TEXT UNIQUE,
                telegram_id INTEGER UNIQUE
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
                last_report TEXT,
                carried_from_previous INTEGER DEFAULT 0,
                confirmed INTEGER DEFAULT 0,
                sent_at TEXT,
                working_date TEXT
            )
        """)
        # اضافه کردن ستون working_date اگر وجود نداشته باشد
        try:
            await db.execute("ALTER TABLE tasks ADD COLUMN working_date TEXT")
        except:
            pass

        await db.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER,
                reported_percent INTEGER,
                text_report TEXT,
                media_file_id TEXT,
                created_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        await db.commit()

async def set_setting(key, value):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
        await db.commit()

async def get_setting(key, default=None):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = await cursor.fetchone()
        return row[0] if row else default

async def add_or_update_user(username=None, full_name=None, telegram_id=None):
    async with aiosqlite.connect(DB_NAME) as db:
        if telegram_id:
            cursor = await db.execute("SELECT id FROM users WHERE telegram_id = ?", (telegram_id,))
            exists = await cursor.fetchone()
            if exists:
                if username:
                    await db.execute(
                        "UPDATE users SET username = ?, full_name = ? WHERE telegram_id = ?",
                        (username.lower().replace("@", ""), full_name or "نامشخص", telegram_id)
                    )
            else:
                if username:
                    clean_username = username.lower().replace("@", "")
                    cursor = await db.execute("SELECT id FROM users WHERE username = ?", (clean_username,))
                    exists_by_user = await cursor.fetchone()
                    if exists_by_user:
                        await db.execute(
                            "UPDATE users SET telegram_id = ?, full_name = ? WHERE username = ?",
                            (telegram_id, full_name or "نامشخص", clean_username)
                        )
                    else:
                        await db.execute(
                            "INSERT INTO users (full_name, username, telegram_id) VALUES (?, ?, ?)",
                            (full_name or "نامشخص", clean_username, telegram_id)
                        )
                else:
                    await db.execute(
                        "INSERT INTO users (full_name, username, telegram_id) VALUES (?, ?, ?)",
                        (full_name or "نامشخص", "", telegram_id)
                    )
        await db.commit()

async def get_telegram_id_by_username(username: str):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT telegram_id FROM users WHERE username = ?",
            (username.lower().replace("@", ""),)
        )
        row = await cursor.fetchone()
        return row[0] if row else None

async def get_user_info_by_telegram_id(telegram_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT full_name, username FROM users WHERE telegram_id = ?", (telegram_id,)
        )
        return await cursor.fetchone()

async def add_user(full_name: str, username: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (full_name, username) VALUES (?, ?)",
            (full_name, username.lower().replace("@", ""))
        )
        await db.commit()

async def get_all_users():
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT full_name, username, telegram_id FROM users")
        return await cursor.fetchall()

async def add_task(date, time_str, task_name, responsible_username, planned_percent, resources, carried=0, working_date=None):
    async with aiosqlite.connect(DB_NAME) as db:
        now = now_iran().strftime("%Y-%m-%d %H:%M")
        if not working_date:
            working_date = now_iran().strftime("%Y-%m-%d")
        cursor = await db.execute("""
            INSERT INTO tasks (date, time, task_name, responsible_username, planned_percent, resources, carried_from_previous, sent_at, working_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (date, time_str, task_name, responsible_username.lower().replace("@", ""), planned_percent, resources, carried, now, working_date))
        await db.commit()
        return cursor.lastrowid

async def mark_confirmed(task_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE tasks SET confirmed = 1 WHERE id = ?", (task_id,))
        await db.commit()

async def is_confirmed(task_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT confirmed FROM tasks WHERE id = ?", (task_id,))
        row = await cursor.fetchone()
        return row[0] == 1 if row else False

async def get_task(task_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        return await cursor.fetchone()

async def update_task_progress(task_id: int, actual_percent: int, reason: str = None):
    async with aiosqlite.connect(DB_NAME) as db:
        now = now_iran().strftime("%Y-%m-%d %H:%M")
        await db.execute("""
            UPDATE tasks SET actual_percent = ?, reason = ?, last_report = ?, status = ?
            WHERE id = ?
        """, (actual_percent, reason, now, "در حال انجام", task_id))
        await db.commit()

async def add_report(task_id: int, reported_percent: int, text_report: str = None, media_file_id: str = None):
    async with aiosqlite.connect(DB_NAME) as db:
        now = now_iran().strftime("%Y-%m-%d %H:%M")
        await db.execute("""
            INSERT INTO reports (task_id, reported_percent, text_report, media_file_id, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (task_id, reported_percent, text_report, media_file_id, now))
        await db.commit()

async def get_today_tasks(working_date: str):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT * FROM tasks WHERE working_date = ?", (working_date,))
        return await cursor.fetchall()

async def get_reports_for_task(task_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT * FROM reports WHERE task_id = ? ORDER BY created_at", (task_id,))
        return await cursor.fetchall()

# ==================== کیبورد گزارش ====================
def report_keyboard(task_id: int):
    buttons = []
    row = []
    for p in [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]:
        row.append(InlineKeyboardButton(text=f"{p}%", callback_data=f"prog:{task_id}:{p}"))
        if len(row) == 5:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="📝 متن + عکس/فیلم", callback_data=f"text:{task_id}")])
    buttons.append([InlineKeyboardButton(text="🔄 گزارش مجدد همین تسک", callback_data=f"report:{task_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ==================== دستورات ====================
@dp.message(Command("start"))
async def cmd_start(message: Message):
    user = message.from_user
    await add_or_update_user(username=user.username, full_name=user.full_name, telegram_id=user.id)
    if user.id == ADMIN_ID:
        await message.answer(
            "سلام آقای شادلو\nربات آماده است (نسخه با ساعت ایران).\n\n"
            "/adduser نام یوزرنیم\n"
            "/addtask\n"
            "/users\n"
            "/sethours 08:00 17:00"
        )
    else:
        await message.answer("شما به عنوان مسئول ثبت شدید.\nمنتظر تسک‌ها باشید.")

@dp.message(Command("adduser"))
async def cmd_adduser(message: Message):
    if message.from_user.id != ADMIN_ID: return
    try:
        parts = message.text.split(maxsplit=2)
        await add_user(parts[1], parts[2])
        await message.answer(f"✅ {parts[1]} اضافه شد.")
    except:
        await message.answer("فرمت: /adduser نام یوزرنیم")

@dp.message(Command("users"))
async def cmd_users(message: Message):
    if message.from_user.id != ADMIN_ID: return
    users = await get_all_users()
    text = "لیست مسئولین:\n\n"
    for u in users:
        text += f"• {u[0]} → @{u[1]} | ID: {u[2]}\n"
    await message.answer(text or "خالی")

@dp.message(Command("sethours"))
async def cmd_sethours(message: Message):
    if message.from_user.id != ADMIN_ID: return
    try:
        parts = message.text.split()
        start_h, end_h = parts[1], parts[2]
        await set_setting("start_hour", start_h)
        await set_setting("end_hour", end_h)
        await set_setting("hours_date", now_iran().strftime("%Y-%m-%d"))
        await message.answer(f"✅ ساعت کاری تنظیم شد:\nشروع: {start_h}\nپایان: {end_h}")
    except:
        await message.answer("فرمت: /sethours 08:00 17:00")

@dp.message(Command("addtask"))
async def cmd_addtask(message: Message):
    if message.from_user.id != ADMIN_ID: return
    try:
        text = message.text.replace("/addtask", "").strip()
        parts = re.findall(r'"([^"]*)"', text)
        if len(parts) < 2:
            await message.answer("نام تسک و منابع را داخل \" \" بگذارید.")
            return
        task_name, resources = parts[0], parts[1]
        remaining = text
        for p in parts:
            remaining = remaining.replace(f'"{p}"', "")
        rp = remaining.split()
        if len(rp) < 4:
            await message.answer("فرمت ناقص است.")
            return
        date, time_str, username, percent = rp[0], rp[1], rp[2], int(rp[3])
        
        working_date = now_iran().strftime("%Y-%m-%d")
        task_id = await add_task(date, time_str, task_name, username, percent, resources, working_date=working_date)
        send_time = now_iran().strftime("%H:%M")
        
        tg_id = await get_telegram_id_by_username(username)
        if tg_id:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ تأیید دریافت", callback_data=f"confirm:{task_id}")],
                [InlineKeyboardButton(text="📊 گزارش پیشرفت", callback_data=f"report:{task_id}")]
            ])
            await bot.send_message(
                tg_id,
                f"📋 تسک جدید\n\n"
                f"🕐 ساعت ارسال: {send_time}\n"
                f"🆔 #{task_id}\n"
                f"📝 {task_name}\n"
                f"📅 {date} ⏰ {time_str}\n"
                f"📊 پلان: {percent}%\n"
                f"📦 منابع: {resources}\n\n"
                f"لطفاً تأیید دریافت را بزنید.",
                reply_markup=kb
            )
            await message.answer(f"✅ تسک #{task_id} برای @{username} ارسال شد.\nساعت ارسال (ایران): {send_time}")
            asyncio.create_task(reminder_and_alarm(task_id, tg_id, username, task_name, send_time))
        else:
            await message.answer(f"✅ تسک ثبت شد ولی آیدی @{username} پیدا نشد. او باید /start کند.")
    except Exception as e:
        await message.answer(f"خطا: {e}")

@dp.callback_query(F.data.startswith("confirm:"))
async def process_confirm(callback: CallbackQuery):
    task_id = int(callback.data.split(":")[1])
    await mark_confirmed(task_id)
    confirm_time = now_iran().strftime("%H:%M")

    # ویرایش پیام قبلی
    await callback.message.edit_text(
        callback.message.text + f"\n\n✅ دریافت در ساعت {confirm_time} تأیید شد."
    )

    # ارسال پیام جدید با دکمه‌های گزارش (تا همیشه در دسترس باشد)
    task = await get_task(task_id)
    if task:
        await callback.message.answer(
            f"📊 حالا می‌توانید گزارش پیشرفت تسک #{task_id} را بدهید:\n"
            f"📝 {task[3]}\n"
            f"پلان: {task[5]}%\n\n"
            f"هر ساعت می‌توانید دوباره گزارش دهید:",
            reply_markup=report_keyboard(task_id)
        )

    await callback.answer("تأیید شد. دکمه‌های گزارش برای شما ارسال شد.")


@dp.callback_query(F.data.startswith("report:"))
async def start_report(callback: CallbackQuery):
    task_id = int(callback.data.split(":")[1])
    task = await get_task(task_id)
    if not task:
        await callback.answer("تسک پیدا نشد", show_alert=True)
        return
    await callback.message.answer(
        f"📊 گزارش پیشرفت تسک #{task_id}\n"
        f"📝 {task[3]}\n"
        f"پلان: {task[5]}%\n\n"
        f"درصد فعلی را انتخاب کنید یا متن/عکس بفرستید:",
        reply_markup=report_keyboard(task_id)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("prog:"))
async def process_percent(callback: CallbackQuery):
    _, task_id, percent = callback.data.split(":")
    task_id, percent = int(task_id), int(percent)
    task = await get_task(task_id)
    if not task:
        return
    planned = task[5]
    calculated = round(planned * percent / 100, 1)
    await update_task_progress(task_id, percent)
    await add_report(task_id, percent)

    user_info = await get_user_info_by_telegram_id(callback.from_user.id)
    name = user_info[0] if user_info else callback.from_user.full_name
    username = user_info[1] if user_info else (callback.from_user.username or "بدون یوزرنیم")

    report_time = now_iran().strftime("%H:%M")
    text = (
        f"📊 گزارش پیشرفت\n\n"
        f"👤 مسئول: {name} (@{username})\n"
        f"🆔 تسک #{task_id}: {task[3]}\n"
        f"📈 درصد اعلام‌شده: {percent}%\n"
        f"🎯 پلان: {planned}%\n"
        f"🧮 پیشرفت محاسبه‌شده: {calculated}%\n"
        f"🕐 ساعت: {report_time}"
    )
    if calculated < planned:
        text += "\n⚠️ عقب از برنامه"
        await callback.message.answer("لطفاً دلیل یا عکس/فیلم بفرستید:")
    await bot.send_message(ADMIN_ID, text)
    await callback.message.answer(
        f"✅ گزارش {percent}% ثبت شد.\nبرای گزارش بعدی دوباره دکمه زیر را بزنید:",
        reply_markup=report_keyboard(task_id)
    )
    await callback.answer(f"{percent}% ثبت شد")

@dp.callback_query(F.data.startswith("text:"))
async def ask_text(callback: CallbackQuery):
    task_id = int(callback.data.split(":")[1])
    await callback.message.answer(f"توضیح یا عکس/فیلم مربوط به تسک #{task_id} را بفرستید.")
    await callback.answer()

@dp.message(F.text | F.photo | F.video | F.document)
async def handle_media(message: Message):
    if message.from_user.id == ADMIN_ID:
        return
    user_info = await get_user_info_by_telegram_id(message.from_user.id)
    name = user_info[0] if user_info else message.from_user.full_name
    username = user_info[1] if user_info else (message.from_user.username or "بدون یوزرنیم")
    caption = message.caption or message.text or "بدون توضیح"
    header = f"📎 گزارش از {name} (@{username})\n🕐 {now_iran().strftime('%H:%M')}\n\n{caption}"
    if message.photo:
        await bot.send_photo(ADMIN_ID, message.photo[-1].file_id, caption=header)
    elif message.video:
        await bot.send_video(ADMIN_ID, message.video.file_id, caption=header)
    elif message.document:
        await bot.send_document(ADMIN_ID, message.document.file_id, caption=header)
    else:
        await bot.send_message(ADMIN_ID, header)
    await message.answer("✅ گزارش شما ارسال شد.\nبرای گزارش بعدی از دکمه گزارش پیشرفت استفاده کنید.")

async def reminder_and_alarm(task_id, tg_id, username, task_name, send_time):
    for i in range(5):
        await asyncio.sleep(600)
        if await is_confirmed(task_id):
            return
        try:
            await bot.send_message(tg_id, f"⏰ یادآوری ({i+1}/5)\nتسک «{task_name}» را تأیید کنید.")
        except:
            pass
    await asyncio.sleep(600)
    if not await is_confirmed(task_id):
        await bot.send_message(
            ADMIN_ID,
            f"🔴 آلارم\n@{username} تسک «{task_name}» را تأیید نکرد.\nساعت ارسال: {send_time}"
        )

# ==================== وظایف زمان‌بندی شده ====================
async def daily_hours_ask():
    while True:
        now = now_iran()
        target = now.replace(hour=5, minute=0, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        await asyncio.sleep((target - now).total_seconds())
        try:
            await bot.send_message(
                ADMIN_ID,
                "⏰ ساعت ۵ صبح است.\nلطفاً ساعت شروع و پایان کارگاه امروز را وارد کنید:\n\nمثال:\n/sethours 08:00 17:00"
            )
        except:
            pass

async def end_of_day_report():
    while True:
        await asyncio.sleep(60)
        end_hour = await get_setting("end_hour")
        hours_date = await get_setting("hours_date")
        if not end_hour or not hours_date:
            continue
        now = now_iran()
        if hours_date != now.strftime("%Y-%m-%d"):
            continue
        try:
            h, m = map(int, end_hour.split(":"))
            end_time = now.replace(hour=h, minute=m, second=0, microsecond=0)
            report_time = end_time + timedelta(minutes=30)
            if now >= report_time and now < report_time + timedelta(minutes=1):
                await send_daily_summary(hours_date)
        except:
            pass

async def send_daily_summary(working_date: str):
    tasks = await get_today_tasks(working_date)
    if not tasks:
        await bot.send_message(ADMIN_ID, "گزارش پایان روز: هیچ تسکی برای امروز ثبت نشده.")
        return

    summary = f"📊 گزارش نهایی روز {working_date}\n\n"
    stats = {}

    for task in tasks:
        task_id = task[0]
        name = task[3]
        username = task[4]
        planned = task[5]
        actual = task[8] or 0
        reports = await get_reports_for_task(task_id)

        if username not in stats:
            stats[username] = {"count": 0}
        stats[username]["count"] += 1

        summary += f"🔹 تسک #{task_id}: {name}\n"
        summary += f"   مسئول: @{username}\n"
        summary += f"   پلان: {planned}% | واقعی: {actual}% | تفاوت: {planned - actual}%\n"
        if reports:
            summary += "   گزارش‌های امروز:\n"
            for r in reports:
                summary += f"     • {r[5]} → {r[2]}%\n"
        summary += "\n"

    summary += "\n📈 آمار تعداد تسک‌ها:\n"
    for u, data in stats.items():
        summary += f"• @{u}: {data['count']} تسک\n"

    await bot.send_message(ADMIN_ID, summary)

    # انتقال خودکار تسک‌های ناقص
    for task in tasks:
        if (task[8] or 0) < task[5]:
            remaining = task[5] - (task[8] or 0)
            tomorrow = (now_iran() + timedelta(days=1)).strftime("%Y-%m-%d")
            await add_task(
                tomorrow, task[2], f"[از روز قبل] {task[3]}",
                task[4], remaining, task[6], carried=1, working_date=tomorrow
            )
    await bot.send_message(ADMIN_ID, "✅ تسک‌های ناقص به‌صورت خودکار برای فردا ثبت شدند.")

async def main():
    await init_db()
    asyncio.create_task(daily_hours_ask())
    asyncio.create_task(end_of_day_report())
    print("ربات روشن شد (نسخه کامل + ساعت ایران)...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())