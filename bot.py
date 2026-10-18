import asyncio
import logging
import re
import aiosqlite
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
import os

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID"))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
logging.basicConfig(level=logging.INFO)

DB_NAME = "/data/shadloo_bot.db"

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
                media_file_id TEXT,
                confirmed INTEGER DEFAULT 0,
                sent_at TEXT
            )
        """)
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
        await db.commit()

async def add_or_update_user(username=None, full_name=None, telegram_id=None):
    async with aiosqlite.connect(DB_NAME) as db:
        if telegram_id:
            cursor = await db.execute("SELECT id FROM users WHERE telegram_id = ?", (telegram_id,))
            exists = await cursor.fetchone()
            if exists:
                if username:
                    await db.execute("UPDATE users SET username = ? WHERE telegram_id = ?",
                                     (username.lower().replace("@", ""), telegram_id))
            else:
                await db.execute(
                    "INSERT INTO users (full_name, username, telegram_id) VALUES (?, ?, ?)",
                    (full_name or "نامشخص", (username or "").lower().replace("@", ""), telegram_id)
                )
        await db.commit()

async def get_telegram_id_by_username(username: str):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT telegram_id FROM users WHERE username = ?",
                                  (username.lower().replace("@", ""),))
        row = await cursor.fetchone()
        return row[0] if row else None

async def get_user_info_by_telegram_id(telegram_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT full_name, username FROM users WHERE telegram_id = ?", (telegram_id,))
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

async def add_task(date, time, task_name, responsible_username, planned_percent, resources, carried=0):
    async with aiosqlite.connect(DB_NAME) as db:
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        cursor = await db.execute("""
            INSERT INTO tasks (date, time, task_name, responsible_username, planned_percent, resources, carried_from_previous, sent_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (date, time, task_name, responsible_username.lower().replace("@", ""), planned_percent, resources, carried, now))
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
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        await db.execute("""
            UPDATE tasks SET actual_percent = ?, reason = ?, last_report = ?, status = ?
            WHERE id = ?
        """, (actual_percent, reason, now, "در حال انجام", task_id))
        await db.commit()

async def add_report(task_id: int, reported_percent: int, text_report: str = None, media_file_id: str = None):
    async with aiosqlite.connect(DB_NAME) as db:
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        await db.execute("""
            INSERT INTO reports (task_id, reported_percent, text_report, media_file_id, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (task_id, reported_percent, text_report, media_file_id, now))
        await db.commit()

def percent_keyboard(task_id: int):
    buttons = []
    row = []
    for p in [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]:
        row.append(InlineKeyboardButton(text=f"{p}%", callback_data=f"prog:{task_id}:{p}"))
        if len(row) == 5:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="📝 توضیح + عکس/فیلم", callback_data=f"text:{task_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@dp.message(Command("start"))
async def cmd_start(message: Message):
    user = message.from_user
    await add_or_update_user(username=user.username, full_name=user.full_name, telegram_id=user.id)
    if user.id == ADMIN_ID:
        await message.answer("سلام آقای شادلو\nربات آماده است.\n\n/adduser\n/addtask\n/users")
    else:
        await message.answer("شما به عنوان مسئول ثبت شدید.")

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
        for p in parts: remaining = remaining.replace(f'"{p}"', "")
        rp = remaining.split()
        if len(rp) < 4:
            await message.answer("فرمت ناقص است.")
            return
        date, time, username, percent = rp[0], rp[1], rp[2], int(rp[3])
        
        task_id = await add_task(date, time, task_name, username, percent, resources)
        send_time = datetime.now().strftime("%H:%M")
        
        tg_id = await get_telegram_id_by_username(username)
        if tg_id:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ تأیید دریافت", callback_data=f"confirm:{task_id}")],
                [InlineKeyboardButton(text="📊 گزارش پیشرفت", callback_data=f"report:{task_id}")]
            ])
            await bot.send_message(
                tg_id,
                f"📋 تسک جدید\n\n🕐 ساعت ارسال: {send_time}\n🆔 #{task_id}\n📝 {task_name}\n📅 {date} ⏰ {time}\n📊 پلان: {percent}%\n📦 منابع: {resources}\n\nلطفاً تأیید دریافت را بزنید.",
                reply_markup=kb
            )
            await message.answer(f"✅ تسک #{task_id} برای @{username} ارسال شد.")
            asyncio.create_task(reminder_and_alarm(task_id, tg_id, username, task_name, send_time))
        else:
            await message.answer(f"✅ تسک ثبت شد ولی آیدی @{username} پیدا نشد.")
    except Exception as e:
        await message.answer(f"خطا: {e}")

@dp.callback_query(F.data.startswith("confirm:"))
async def process_confirm(callback: CallbackQuery):
    task_id = int(callback.data.split(":")[1])
    await mark_confirmed(task_id)
    await callback.message.edit_text(callback.message.text + f"\n\n✅ دریافت در ساعت {datetime.now().strftime('%H:%M')} تأیید شد.")
    await callback.answer("تأیید شد.")

@dp.callback_query(F.data.startswith("report:"))
async def start_report(callback: CallbackQuery):
    task_id = int(callback.data.split(":")[1])
    task = await get_task(task_id)
    if not task:
        await callback.answer("تسک پیدا نشد", show_alert=True)
        return
    await callback.message.answer(
        f"📊 گزارش پیشرفت تسک #{task_id}\n📝 {task[3]}\nپلان: {task[5]}%\n\nدرصد را انتخاب کنید:",
        reply_markup=percent_keyboard(task_id)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("prog:"))
async def process_percent(callback: CallbackQuery):
    _, task_id, percent = callback.data.split(":")
    task_id, percent = int(task_id), int(percent)
    task = await get_task(task_id)
    if not task: return
    planned = task[5]
    calculated = round(planned * percent / 100, 1)
    await update_task_progress(task_id, percent)
    await add_report(task_id, percent)
    user_info = await get_user_info_by_telegram_id(callback.from_user.id)
    name = user_info[0] if user_info else callback.from_user.full_name
    username = user_info[1] if user_info else callback.from_user.username
    text = f"📊 گزارش\n👤 {name} (@{username})\n🆔 تسک #{task_id}: {task[3]}\n📈 {percent}%\n🎯 پلان: {planned}%\n🧮 محاسبه: {calculated}%"
    if calculated < planned:
        text += "\n⚠️ عقب از برنامه"
        await callback.message.answer("دلیل عقب‌ماندگی را بنویسید یا عکس بفرستید:")
    await bot.send_message(ADMIN_ID, text)
    await callback.answer(f"{percent}% ثبت شد")

@dp.callback_query(F.data.startswith("text:"))
async def ask_text(callback: CallbackQuery):
    await callback.message.answer("توضیح یا عکس/فیلم را بفرستید.")
    await callback.answer()

@dp.message(F.text | F.photo | F.video | F.document)
async def handle_media(message: Message):
    if message.from_user.id == ADMIN_ID: return
    user_info = await get_user_info_by_telegram_id(message.from_user.id)
    name = user_info[0] if user_info else message.from_user.full_name
    username = user_info[1] if user_info else message.from_user.username
    caption = message.caption or message.text or "بدون توضیح"
    header = f"📎 از {name} (@{username})\n\n{caption}"
    if message.photo:
        await bot.send_photo(ADMIN_ID, message.photo[-1].file_id, caption=header)
    elif message.video:
        await bot.send_video(ADMIN_ID, message.video.file_id, caption=header)
    elif message.document:
        await bot.send_document(ADMIN_ID, message.document.file_id, caption=header)
    else:
        await bot.send_message(ADMIN_ID, header)
    await message.answer("✅ ارسال شد.")

async def reminder_and_alarm(task_id, tg_id, username, task_name, send_time):
    for i in range(5):
        await asyncio.sleep(600)
        if await is_confirmed(task_id): return
        try:
            await bot.send_message(tg_id, f"⏰ یادآوری ({i+1}/5)\nتسک «{task_name}» را تأیید کنید.")
        except: pass
    await asyncio.sleep(600)
    if not await is_confirmed(task_id):
        await bot.send_message(ADMIN_ID, f"🔴 آلارم\n@{username} تسک «{task_name}» را تأیید نکرد.\nساعت ارسال: {send_time}")

async def main():
    await init_db()
    print("ربات روشن شد...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())