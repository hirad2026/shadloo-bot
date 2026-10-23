import asyncio
import logging
import aiosqlite
import json
import re
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

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

# ==================== FSM ====================
class NewTask(StatesGroup):
    task_name = State()
    planned_percent = State()
    location = State()
    responsible = State()
    manpower_item = State()
    manpower_more = State()
    material_item = State()
    material_more = State()
    machine_item = State()
    machine_more = State()
    tool_item = State()
    tool_more = State()
    attach_ask = State()
    attach_file = State()
    attach_caption = State()

class AddUser(StatesGroup):
    waiting_photo = State()

class ResourceReport(StatesGroup):
    waiting_resource = State()
    waiting_percent = State()

class ReportAttach(StatesGroup):
    waiting_attach = State()

# ==================== دیتابیس ====================
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT,
                username TEXT UNIQUE,
                telegram_id INTEGER UNIQUE,
                photo_file_id TEXT
            )
        """)
        try:
            await db.execute("ALTER TABLE users ADD COLUMN photo_file_id TEXT")
        except:
            pass

        await db.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                time TEXT,
                task_name TEXT,
                responsible_username TEXT,
                planned_percent INTEGER DEFAULT 0,
                location TEXT,
                resources TEXT,
                status TEXT DEFAULT 'در انتظار',
                actual_percent INTEGER DEFAULT 0,
                reason TEXT,
                last_report TEXT,
                carried_from_previous INTEGER DEFAULT 0,
                confirmed INTEGER DEFAULT 0,
                sent_at TEXT,
                working_date TEXT,
                attach_file_id TEXT,
                attach_caption TEXT
            )
        """)
        for col in ["working_date", "location", "attach_file_id", "attach_caption"]:
            try:
                await db.execute(f"ALTER TABLE tasks ADD COLUMN {col} TEXT")
            except:
                pass

        await db.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER,
                reported_percent INTEGER,
                text_report TEXT,
                media_file_id TEXT,
                resources_actual TEXT,
                created_at TEXT
            )
        """)
        try:
            await db.execute("ALTER TABLE reports ADD COLUMN resources_actual TEXT")
        except:
            pass

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

async def add_or_update_user(username=None, full_name=None, telegram_id=None, photo_file_id=None):
    async with aiosqlite.connect(DB_NAME) as db:
        clean_username = (username or "").lower().replace("@", "").strip() if username else None
        if telegram_id:
            cursor = await db.execute("SELECT id FROM users WHERE telegram_id = ?", (telegram_id,))
            if await cursor.fetchone():
                await db.execute("""
                    UPDATE users SET
                        full_name = COALESCE(?, full_name),
                        username = COALESCE(?, username),
                        photo_file_id = COALESCE(?, photo_file_id)
                    WHERE telegram_id = ?
                """, (full_name, clean_username, photo_file_id, telegram_id))
            else:
                if clean_username:
                    cursor = await db.execute("SELECT id FROM users WHERE username = ?", (clean_username,))
                    if await cursor.fetchone():
                        await db.execute("""
                            UPDATE users SET
                                telegram_id = ?,
                                full_name = COALESCE(?, full_name),
                                photo_file_id = COALESCE(?, photo_file_id)
                            WHERE username = ?
                        """, (telegram_id, full_name, photo_file_id, clean_username))
                    else:
                        await db.execute(
                            "INSERT INTO users (full_name, username, telegram_id, photo_file_id) VALUES (?,?,?,?)",
                            (full_name or "نامشخص", clean_username, telegram_id, photo_file_id)
                        )
                else:
                    await db.execute(
                        "INSERT INTO users (full_name, username, telegram_id, photo_file_id) VALUES (?,?,?,?)",
                        (full_name or "نامشخص", "", telegram_id, photo_file_id)
                    )
        await db.commit()

async def get_telegram_id_by_username(username: str):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT telegram_id FROM users WHERE username = ?",
            (username.lower().replace("@", "").strip(),)
        )
        row = await cursor.fetchone()
        return row[0] if row else None

async def get_user_info_by_telegram_id(telegram_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT full_name, username, photo_file_id FROM users WHERE telegram_id = ?", (telegram_id,)
        )
        return await cursor.fetchone()

async def get_user_by_username(username: str):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT full_name, username, photo_file_id, telegram_id FROM users WHERE username = ?",
            (username.lower().replace("@", "").strip(),)
        )
        return await cursor.fetchone()

async def add_user(full_name: str, username: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (full_name, username) VALUES (?, ?)",
            (full_name, username.lower().replace("@", "").strip())
        )
        await db.commit()

async def update_user_photo(username: str, photo_file_id: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "UPDATE users SET photo_file_id = ? WHERE username = ?",
            (photo_file_id, username.lower().replace("@", "").strip())
        )
        await db.commit()

async def get_all_users():
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT full_name, username, telegram_id, photo_file_id FROM users")
        return await cursor.fetchall()

async def add_task_full(data: dict):
    async with aiosqlite.connect(DB_NAME) as db:
        now = now_iran().strftime("%Y-%m-%d %H:%M")
        working_date = now_iran().strftime("%Y-%m-%d")
        resources_json = json.dumps(data.get("resources", {}), ensure_ascii=False)
        cursor = await db.execute("""
            INSERT INTO tasks (
                date, time, task_name, responsible_username, planned_percent, location,
                resources, sent_at, working_date, attach_file_id, attach_caption
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (
            working_date, now.split()[1], data["task_name"],
            data["responsible"].lower().replace("@", ""),
            data["planned_percent"], data.get("location"),
            resources_json, now, working_date,
            data.get("attach_file_id"), data.get("attach_caption")
        ))
        await db.commit()
        return cursor.lastrowid

async def get_task(task_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        return await cursor.fetchone()

async def mark_confirmed(task_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE tasks SET confirmed = 1 WHERE id = ?", (task_id,))
        await db.commit()

async def is_confirmed(task_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT confirmed FROM tasks WHERE id = ?", (task_id,))
        row = await cursor.fetchone()
        return row[0] == 1 if row else False

async def update_task_progress(task_id: int, actual_percent: int):
    async with aiosqlite.connect(DB_NAME) as db:
        now = now_iran().strftime("%Y-%m-%d %H:%M")
        await db.execute(
            "UPDATE tasks SET actual_percent = ?, last_report = ?, status = 'در حال انجام' WHERE id = ?",
            (actual_percent, now, task_id)
        )
        await db.commit()

async def add_report(task_id: int, reported_percent: int, text_report=None, media_file_id=None, resources_actual=None):
    async with aiosqlite.connect(DB_NAME) as db:
        now = now_iran().strftime("%Y-%m-%d %H:%M")
        await db.execute("""
            INSERT INTO reports (task_id, reported_percent, text_report, media_file_id, resources_actual, created_at)
            VALUES (?,?,?,?,?,?)
        """, (task_id, reported_percent, text_report, media_file_id, resources_actual, now))
        await db.commit()

async def get_today_tasks(working_date: str):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT * FROM tasks WHERE working_date = ?", (working_date,))
        return await cursor.fetchall()

async def get_reports_for_task(task_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT * FROM reports WHERE task_id = ? ORDER BY created_at", (task_id,))
        return await cursor.fetchall()

async def get_tasks_by_date_range(start_date: str, end_date: str):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT * FROM tasks
            WHERE working_date >= ? AND working_date <= ?
            ORDER BY id DESC
        """, (start_date, end_date))
        return await cursor.fetchall()

async def get_tasks_by_username(username: str, start_date: str = None, end_date: str = None):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        clean = username.lower().replace("@", "").strip()
        if start_date and end_date:
            cursor = await db.execute("""
                SELECT * FROM tasks
                WHERE responsible_username = ? AND working_date >= ? AND working_date <= ?
                ORDER BY id DESC
            """, (clean, start_date, end_date))
        else:
            cursor = await db.execute("""
                SELECT * FROM tasks
                WHERE responsible_username = ?
                ORDER BY id DESC LIMIT 50
            """, (clean,))
        return await cursor.fetchall()

async def get_reports_by_task_ids(task_ids: list):
    if not task_ids:
        return []
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        placeholders = ",".join("?" * len(task_ids))
        cursor = await db.execute(
            f"SELECT * FROM reports WHERE task_id IN ({placeholders}) ORDER BY created_at DESC",
            task_ids
        )
        return await cursor.fetchall()

# ==================== توابع کمکی ====================
def yes_no_keyboard(prefix=""):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="بله", callback_data=f"{prefix}yes"),
            InlineKeyboardButton(text="خیر", callback_data=f"{prefix}no")
        ]
    ])

def calc_remaining(planned: int, actual: int) -> int:
    return max(0, planned - (actual or 0))

def format_task_line(task) -> str:
    planned = task['planned_percent'] or 0
    actual = task['actual_percent'] or 0
    remaining = calc_remaining(planned, actual)
    calculated = round(planned * actual / 100, 1) if actual else 0
    loc = task['location'] or "-"
    return (
        f"🔹 #{task['id']}: {task['task_name']}\n"
        f"   📍 {loc}\n"
        f"   🎯 پلان: {planned}% | ✅ واقعی: {actual}% | 📉 باقی: {remaining}%\n"
        f"   🧮 سهم از پروژه: {calculated}%\n"
        f"   👤 @{task['responsible_username']} | وضعیت: {task['status'] or '-'}\n"
    )

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
    buttons.append([InlineKeyboardButton(text="📝 فقط متن/عکس/فیلم", callback_data=f"text:{task_id}")])
    buttons.append([InlineKeyboardButton(text="🔄 گزارش مجدد", callback_data=f"report:{task_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def build_resource_list(resources: dict):
    items = []
    if resources.get("manpower"):
        for x in resources["manpower"]:
            items.append(("نیروی انسانی", x))
    if resources.get("materials"):
        for x in resources["materials"]:
            items.append(("مصالح", x))
    if resources.get("machines"):
        for x in resources["machines"]:
            items.append(("ماشین‌آلات", x))
    if resources.get("tools"):
        for x in resources["tools"]:
            items.append(("ابزارآلات", x))
    return items

async def get_expected_percent(planned: int) -> str:
    start_h = await get_setting("start_hour")
    end_h = await get_setting("end_hour")
    if not start_h or not end_h:
        return "ساعت کاری تنظیم نشده (/sethours)"
    try:
        now = now_iran()
        sh, sm = map(int, start_h.split(":"))
        eh, em = map(int, end_h.split(":"))
        start = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
        end = now.replace(hour=eh, minute=em, second=0, microsecond=0)
        if now < start:
            return f"هنوز ساعت کاری شروع نشده (شروع: {start_h})"
        if now >= end:
            return f"ساعت کاری تمام شده — باید به {planned}% رسیده باشید"
        total = (end - start).total_seconds() / 60
        elapsed = (now - start).total_seconds() / 60
        expected = round((elapsed / total) * planned, 1)
        return f"تا این لحظه باید حدود {expected}% پیشرفت کرده باشید (از {planned}% پلان)"
    except:
        return "خطا در محاسبه درصد مورد انتظار"



# ==================== دستورات پایه ====================
@dp.message(Command("start"))
async def cmd_start(message: Message):
    user = message.from_user
    await add_or_update_user(
        username=user.username,
        full_name=user.full_name,
        telegram_id=user.id
    )
    if user.id == ADMIN_ID:
        await message.answer(
            "سلام آقای شادلو\nربات آماده است.\n\n"
            "/newtask → ثبت تسک جدید\n"
            "/adduser نام یوزرنیم\n"
            "/users\n"
            "/link یوزرنیم آیدی\n"
            "/deluser یوزرنیم\n"
            "/sethours 08:00 17:00"
        )
    else:
        await message.answer("شما به عنوان مسئول ثبت شدید.\nمنتظر تسک‌ها باشید.")

@dp.message(Command("team"))
async def cmd_team(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    users = await get_all_users()
    if not users:
        await message.answer("هیچ مسئولی ثبت نشده.")
        return

    buttons = []
    for u in users:
        full_name, username, tg_id, photo = u[0], u[1], u[2], u[3]
        label = f"{full_name} (@{username})"
        buttons.append([InlineKeyboardButton(
            text=label,
            callback_data=f"teamuser:{username}"
        )])

    await message.answer(
        "👷 لیست مسئولین — یکی را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )

@dp.message(Command("adduser"))
async def cmd_adduser(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        parts = message.text.split(maxsplit=2)
        full_name, username = parts[1], parts[2]
        await add_user(full_name, username)
        await state.update_data(pending_username=username.lower().replace("@", "").strip())
        await state.set_state(AddUser.waiting_photo)
        await message.answer(f"✅ {full_name} اضافه شد.\nحالا عکس مسئول را بفرستید (یا بنویسید «ندارد»):")
    except:
        await message.answer("فرمت: /adduser نام یوزرنیم")

@dp.message(AddUser.waiting_photo, F.photo)
async def process_user_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    username = data.get("pending_username")
    await update_user_photo(username, message.photo[-1].file_id)
    await state.clear()
    await message.answer("✅ عکس مسئول ذخیره شد.")

@dp.message(AddUser.waiting_photo, F.text)
async def process_user_photo_skip(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("عکس ذخیره نشد.")

@dp.message(Command("users"))
async def cmd_users(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    users = await get_all_users()
    text = "لیست مسئولین:\n\n"
    for u in users:
        text += f"• {u[0]} → @{u[1]} | ID: {u[2]}\n"
    await message.answer(text or "خالی")

@dp.message(Command("link"))
async def cmd_link(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        parts = message.text.split()
        username = parts[1].replace("@", "").lower()
        telegram_id = int(parts[2])
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("UPDATE users SET telegram_id = ? WHERE username = ?", (telegram_id, username))
            await db.commit()
        await message.answer(f"✅ @{username} به آیدی {telegram_id} وصل شد.")
    except Exception as e:
        await message.answer(f"فرمت: /link irancivil2023 6384495297\nخطا: {e}")

@dp.message(Command("deluser"))
async def cmd_deluser(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        username = message.text.split(maxsplit=1)[1].replace("@", "").lower()
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("DELETE FROM users WHERE username = ?", (username,))
            await db.commit()
        await message.answer(f"✅ @{username} حذف شد.")
    except:
        await message.answer("فرمت: /deluser یوزرنیم")

@dp.message(Command("sethours"))
async def cmd_sethours(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        parts = message.text.split()
        await set_setting("start_hour", parts[1])
        await set_setting("end_hour", parts[2])
        await set_setting("hours_date", now_iran().strftime("%Y-%m-%d"))
        await message.answer(f"✅ ساعت کاری: {parts[1]} تا {parts[2]}")
    except:
        await message.answer("فرمت: /sethours 08:00 17:00")

# ==================== /newtask ====================
@dp.message(Command("newtask"))
async def cmd_newtask(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await state.clear()
    await state.set_state(NewTask.task_name)
    await message.answer("📝 نام فعالیت مورد نظرتان چیست؟")

@dp.message(NewTask.task_name)
async def process_task_name(message: Message, state: FSMContext):
    await state.update_data(task_name=message.text.strip())
    await state.set_state(NewTask.planned_percent)
    await message.answer("📊 درصد پیشرفت برنامه‌ای را وارد کنید (فقط عدد):")

@dp.message(NewTask.planned_percent)
async def process_percent_input(message: Message, state: FSMContext):
    try:
        percent = int(message.text.strip())
        await state.update_data(planned_percent=percent)
        await state.set_state(NewTask.location)
        await message.answer("📍 موقعیت این تسک کجاست؟\nمثال: طبقه دوم ساختمان شماره ۳ کارگاه دوم")
    except:
        await message.answer("فقط عدد وارد کنید.")

@dp.message(NewTask.location)
async def process_location(message: Message, state: FSMContext):
    await state.update_data(location=message.text.strip())
    await state.set_state(NewTask.responsible)
    await message.answer("👤 نام و یوزرنیم مسئول را وارد کنید:\nمثال: علی رضایی @ali_rezaei")

@dp.message(NewTask.responsible)
async def process_responsible(message: Message, state: FSMContext):
    await state.update_data(responsible=message.text.strip())
    await state.update_data(resources={"manpower": [], "materials": [], "machines": [], "tools": []})
    await state.set_state(NewTask.manpower_item)
    await message.answer("👷 نیروی انسانی مورد نیاز:\nنوع/تخصص + تعداد\nمثال: استادکار بنا ۴ نفر")

@dp.message(NewTask.manpower_item)
async def process_manpower(message: Message, state: FSMContext):
    data = await state.get_data()
    resources = data["resources"]
    resources["manpower"].append(message.text.strip())
    await state.update_data(resources=resources)
    await state.set_state(NewTask.manpower_more)
    await message.answer("آیا نیروی انسانی دیگری نیاز است؟", reply_markup=yes_no_keyboard("mp_"))

@dp.callback_query(F.data.startswith("teamuser:"))
async def process_team_user(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    username = callback.data.split(":", 1)[1]
    await callback.answer()

    user = await get_user_by_username(username)
    if not user:
        await callback.message.answer("مسئول پیدا نشد.")
        return

    full_name, uname, photo_id, tg_id = user[0], user[1], user[2], user[3]
    today = now_iran().strftime("%Y-%m-%d")

    tasks = await get_tasks_by_username(username, today, today)
    text = (
        f"👤 مسئول: {full_name} (@{uname})\n"
        f"📅 گزارش امروز ({today})\n"
        f"تعداد تسک امروز: {len(tasks)}\n\n"
    )

    if not tasks:
        text += "هیچ تسکی برای امروز ثبت نشده."
    else:
        for t in tasks:
            text += format_task_line(t) + "\n"

        # آخرین گزارش‌ها
        task_ids = [t['id'] for t in tasks]
        reports = await get_reports_by_task_ids(task_ids)
        if reports:
            text += "\n📝 آخرین گزارش‌ها:\n"
            for r in reports[:10]:
                text += f"• تسک #{r['task_id']} | {r['reported_percent']}% | {r['created_at']}\n"

    # دکمه‌های بازه زمانی
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="امروز", callback_data=f"userperiod:{username}:today"),
            InlineKeyboardButton(text="این هفته", callback_data=f"userperiod:{username}:week"),
            InlineKeyboardButton(text="این ماه", callback_data=f"userperiod:{username}:month"),
        ],
        [InlineKeyboardButton(text="🔙 بازگشت به تیم", callback_data="back_team")]
    ])

    if photo_id:
        try:
            await bot.send_photo(ADMIN_ID, photo_id, caption=text[:1000], reply_markup=kb)
            if len(text) > 1000:
                await bot.send_message(ADMIN_ID, text[1000:], reply_markup=kb)
            return
        except:
            pass

    await callback.message.answer(text, reply_markup=kb)

@dp.callback_query(F.data.startswith("userperiod:"))
async def process_user_period(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    parts = callback.data.split(":")
    username, period = parts[1], parts[2]
    await callback.answer()

    today = now_iran().date()
    if period == "today":
        start = end = today.strftime("%Y-%m-%d")
        title = "امروز"
    elif period == "week":
        start = (today - timedelta(days=today.weekday())).strftime("%Y-%m-%d")
        end = today.strftime("%Y-%m-%d")
        title = "این هفته"
    else:  # month
        start = today.replace(day=1).strftime("%Y-%m-%d")
        end = today.strftime("%Y-%m-%d")
        title = "این ماه"

    user = await get_user_by_username(username)
    full_name = user[0] if user else username
    tasks = await get_tasks_by_username(username, start, end)

    text = f"👤 {full_name} (@{username})\n📅 {title} ({start} تا {end})\nتعداد تسک: {len(tasks)}\n\n"
    if not tasks:
        text += "تسکی یافت نشد."
    else:
        for t in tasks:
            text += format_task_line(t) + "\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 بازگشت به تیم", callback_data="back_team")]
    ])
    await callback.message.answer(text, reply_markup=kb)


@dp.callback_query(F.data == "back_team")
async def back_to_team(callback: CallbackQuery):
    await callback.answer()
    await cmd_team(callback.message)


@dp.callback_query(NewTask.manpower_more, F.data.in_(["mp_yes", "mp_no"]))
async def manpower_more(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if callback.data == "mp_yes":
        await state.set_state(NewTask.manpower_item)
        await callback.message.answer("👷 نیروی انسانی بعدی را بنویسید:")
    else:
        await state.set_state(NewTask.material_item)
        await callback.message.answer("🧱 مصالح مورد نیاز:\nنوع + مقدار + واحد\nمثال: سیمان ۵۰ کیسه")

@dp.message(NewTask.material_item)
async def process_material(message: Message, state: FSMContext):
    data = await state.get_data()
    resources = data["resources"]
    resources["materials"].append(message.text.strip())
    await state.update_data(resources=resources)
    await state.set_state(NewTask.material_more)
    await message.answer("آیا مصالح دیگری نیاز است؟", reply_markup=yes_no_keyboard("mt_"))

@dp.callback_query(NewTask.material_more, F.data.in_(["mt_yes", "mt_no"]))
async def material_more(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if callback.data == "mt_yes":
        await state.set_state(NewTask.material_item)
        await callback.message.answer("🧱 مصالح بعدی را بنویسید:")
    else:
        await state.set_state(NewTask.machine_item)
        await callback.message.answer("🚜 ماشین‌آلات مورد نیاز:\nنوع + تعداد + ساعت کار\nمثال: بیل مکانیکی ۱ دستگاه - ۸ ساعت")

@dp.message(NewTask.machine_item)
async def process_machine(message: Message, state: FSMContext):
    data = await state.get_data()
    resources = data["resources"]
    resources["machines"].append(message.text.strip())
    await state.update_data(resources=resources)
    await state.set_state(NewTask.machine_more)
    await message.answer("آیا ماشین‌آلات دیگری نیاز است؟", reply_markup=yes_no_keyboard("mc_"))

@dp.callback_query(NewTask.machine_more, F.data.in_(["mc_yes", "mc_no"]))
async def machine_more(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if callback.data == "mc_yes":
        await state.set_state(NewTask.machine_item)
        await callback.message.answer("🚜 ماشین‌آلات بعدی را بنویسید:")
    else:
        await state.set_state(NewTask.tool_item)
        await callback.message.answer("🔧 ابزارآلات مورد نیاز:\nنوع + تعداد\nمثال: چکش برقی ۳ عدد")

@dp.message(NewTask.tool_item)
async def process_tool(message: Message, state: FSMContext):
    data = await state.get_data()
    resources = data["resources"]
    resources["tools"].append(message.text.strip())
    await state.update_data(resources=resources)
    await state.set_state(NewTask.tool_more)
    await message.answer("آیا ابزارآلات دیگری نیاز است؟", reply_markup=yes_no_keyboard("tl_"))

@dp.callback_query(NewTask.tool_more, F.data.in_(["tl_yes", "tl_no"]))
async def tool_more(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if callback.data == "tl_yes":
        await state.set_state(NewTask.tool_item)
        await callback.message.answer("🔧 ابزارآلات بعدی را بنویسید:")
    else:
        await state.set_state(NewTask.attach_ask)
        await callback.message.answer(
            "📎 آیا مشخصات فنی / کروکی / آیین‌نامه پیوست می‌کنید؟",
            reply_markup=yes_no_keyboard("at_")
        )

@dp.callback_query(NewTask.attach_ask, F.data.in_(["at_yes", "at_no"]))
async def attach_ask(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if callback.data == "at_yes":
        await state.set_state(NewTask.attach_file)
        await callback.message.answer("فایل را ارسال کنید:")
    else:
        await finish_task(callback.message, state)

@dp.message(NewTask.attach_file, F.document | F.photo | F.video)
async def process_attach_file(message: Message, state: FSMContext):
    if message.document:
        file_id = message.document.file_id
    elif message.photo:
        file_id = message.photo[-1].file_id
    else:
        file_id = message.video.file_id
    await state.update_data(attach_file_id=file_id)
    await state.set_state(NewTask.attach_caption)
    await message.answer("توضیح کوتاه برای فایل بنویسید (یا «ندارد»):")

@dp.message(Command("tasks"))
async def cmd_tasks(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    parts = message.text.split()
    period = parts[1].lower() if len(parts) > 1 else "today"

    today = now_iran().date()
    if period == "today":
        start = end = today.strftime("%Y-%m-%d")
        title = "امروز"
    elif period == "week":
        start = (today - timedelta(days=today.weekday())).strftime("%Y-%m-%d")
        end = today.strftime("%Y-%m-%d")
        title = "این هفته"
    elif period == "month":
        start = today.replace(day=1).strftime("%Y-%m-%d")
        end = today.strftime("%Y-%m-%d")
        title = "این ماه"
    else:
        await message.answer("فرمت:\n/tasks today\n/tasks week\n/tasks month")
        return

    tasks = await get_tasks_by_date_range(start, end)
    text = f"📋 تسک‌های {title}\n📅 {start} تا {end}\nتعداد: {len(tasks)}\n\n"

    if not tasks:
        text += "تسکی ثبت نشده."
    else:
        for t in tasks:
            text += format_task_line(t) + "\n"

    # اگر خیلی طولانی شد، تکه‌تکه بفرست
    if len(text) > 4000:
        for i in range(0, len(text), 4000):
            await message.answer(text[i:i+4000])
    else:
        await message.answer(text)


@dp.message(NewTask.attach_caption)
async def process_attach_caption(message: Message, state: FSMContext):
    caption = None if message.text.strip() == "ندارد" else message.text.strip()
    await state.update_data(attach_caption=caption)
    await finish_task(message, state)

async def finish_task(message: Message, state: FSMContext):
    data = await state.get_data()
    task_id = await add_task_full(data)
    await state.clear()

    res = data.get("resources", {})
    resources_text = ""
    if res.get("manpower"):
        resources_text += "👷 نیروی انسانی برنامه‌ای:\n"
        for x in res["manpower"]:
            resources_text += f"• {x}   → موجود: .....\n"
        resources_text += "\n"
    if res.get("materials"):
        resources_text += "🧱 مصالح برنامه‌ای:\n"
        for x in res["materials"]:
            resources_text += f"• {x}   → موجود: .....\n"
        resources_text += "\n"
    if res.get("machines"):
        resources_text += "🚜 ماشین‌آلات برنامه‌ای:\n"
        for x in res["machines"]:
            resources_text += f"• {x}   → موجود: .....\n"
        resources_text += "\n"
    if res.get("tools"):
        resources_text += "🔧 ابزارآلات برنامه‌ای:\n"
        for x in res["tools"]:
            resources_text += f"• {x}   → موجود: .....\n"
        resources_text += "\n"

    send_time = now_iran().strftime("%H:%M")
    raw = data["responsible"].strip()
    possible = re.findall(r'[a-zA-Z0-9_]{3,}', raw)
    if not possible:
        possible = [raw.split()[-1].strip()]
    possible = [p.lower() for p in possible]

    tg_id = None
    found_username = None
    for uname in possible:
        tg_id = await get_telegram_id_by_username(uname)
        if tg_id:
            found_username = uname
            break

    text = (
        f"📋 تسک جدید\n\n"
        f"🕐 ساعت ارسال: {send_time}\n"
        f"🆔 #{task_id}\n"
        f"📝 {data['task_name']}\n"
        f"📍 موقعیت: {data.get('location', 'ثبت نشده')}\n"
        f"📊 پلان: {data['planned_percent']}%\n\n"
        f"{resources_text}"
    )

    if tg_id:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ تأیید دریافت", callback_data=f"confirm:{task_id}")],
            [InlineKeyboardButton(text="📊 گزارش پیشرفت", callback_data=f"report:{task_id}")]
        ])
        await bot.send_message(tg_id, text, reply_markup=kb)

        if data.get("attach_file_id"):
            try:
                await bot.send_document(tg_id, data["attach_file_id"], caption=data.get("attach_caption") or "فایل پیوست")
            except:
                try:
                    await bot.send_photo(tg_id, data["attach_file_id"], caption=data.get("attach_caption") or "فایل پیوست")
                except:
                    pass

        user_info = await get_user_by_username(found_username) if found_username else None
        resp_name = user_info[0] if user_info else (found_username or "نامشخص")
        await message.answer(
            f"✅ تسک #{task_id} ثبت شد و برای مسئول ارسال گردید:\n\n"
            f"👤 {resp_name}\n@{found_username}"
        )
        asyncio.create_task(reminder_and_alarm(task_id, tg_id, found_username, data["task_name"], send_time))
    else:
        await message.answer(f"✅ تسک #{task_id} ثبت شد ولی آیدی مسئول پیدا نشد.")

# ==================== گزارش مسئول ====================
@dp.callback_query(F.data.startswith("confirm:"))
async def process_confirm(callback: CallbackQuery, state: FSMContext):
    task_id = int(callback.data.split(":")[1])
    await mark_confirmed(task_id)
    confirm_time = now_iran().strftime("%H:%M")
    
    try:
        await callback.message.edit_text(
            callback.message.text + f"\n\n✅ دریافت در ساعت {confirm_time} تأیید شد."
        )
    except:
        pass

    await callback.answer("تأیید شد.")
    
    # حتماً پرسش منابع را شروع کن
    await start_resource_report(callback, state, task_id)

@dp.callback_query(F.data.startswith("report:"))
async def start_report(callback: CallbackQuery, state: FSMContext):
    task_id = int(callback.data.split(":")[1])
    await callback.answer()
    await start_resource_report(callback, state, task_id)

async def start_resource_report(callback: CallbackQuery, state: FSMContext, task_id: int):
    task = await get_task(task_id)
    if not task:
        await callback.message.answer("❌ تسک پیدا نشد.")
        return

    # خواندن با نام ستون (دیگر با شماره ستون کار نمی‌کنیم)
    task_name = task['task_name']
    planned = task['planned_percent']
    location = task['location'] or "-"
    resources_raw = task['resources'] or "{}"

    try:
        resources = json.loads(resources_raw)
        if not isinstance(resources, dict):
            resources = {}
    except Exception as e:
        resources = {}
        await callback.message.answer(f"⚠️ خطا در خواندن منابع: {e}\nمحتوای خام: {resources_raw[:200]}")

    items = build_resource_list(resources)

    # دیباگ موقت
    await callback.message.answer(
        f"🔍 دیباگ:\nتعداد منابع: {len(items)}\nمنابع: {list(resources.keys())}"
    )

    if not items:
        expected = await get_expected_percent(planned)
        await callback.message.answer(
            f"📊 گزارش تسک #{task_id}\n"
            f"📝 {task_name}\n"
            f"📍 {location}\n"
            f"🎯 پلان: {planned}%\n"
            f"⏰ {expected}\n\n"
            f"منبعی ثبت نشده. درصد فعلی را انتخاب کنید:",
            reply_markup=report_keyboard(task_id)
        )
        return

    await state.set_state(ResourceReport.waiting_resource)
    await state.update_data(
        report_task_id=task_id,
        resource_items=items,
        resource_index=0,
        actual_resources=[]
    )

    cat, planned_val = items[0]
    await callback.message.answer(
        f"📋 شروع گزارش منابع تسک #{task_id}\n\n"
        f"دسته: {cat}\n"
        f"برنامه‌ای: {planned_val}\n\n"
        f"❓ مقدار/تعداد موجود (اکچوال) را بنویسید:"
    )

@dp.message(ResourceReport.waiting_resource)
async def process_resource_actual(message: Message, state: FSMContext):
    data = await state.get_data()
    items = data["resource_items"]
    index = data["resource_index"]
    actuals = data.get("actual_resources", [])

    cat, planned_val = items[index]
    actual_val = message.text.strip()
    actuals.append({"category": cat, "planned": planned_val, "actual": actual_val})
    index += 1
    await state.update_data(resource_index=index, actual_resources=actuals)

    if index < len(items):
        cat, planned_val = items[index]
        await message.answer(
            f"دسته: {cat}\n"
            f"برنامه‌ای: {planned_val}\n\n"
            f"❓ مقدار/تعداد موجود (اکچوال) را بنویسید:"
        )
    else:
        task_id = data["report_task_id"]
        task = await get_task(task_id)
        planned = task['planned_percent']
        expected = await get_expected_percent(planned)
        await state.set_state(ResourceReport.waiting_percent)
        await message.answer(
            f"✅ گزارش منابع تمام شد.\n\n"
            f"📊 حالا درصد پیشرفت فعلی را انتخاب کنید:\n"
            f"🎯 پلان: {planned}%\n"
            f"⏰ {expected}",
            reply_markup=report_keyboard(task_id)
        )

@dp.callback_query(F.data.startswith("prog:"))
async def process_percent(callback: CallbackQuery, state: FSMContext):
    _, task_id, percent = callback.data.split(":")
    task_id, percent = int(task_id), int(percent)
    task = await get_task(task_id)
    if not task:
        return

    data = await state.get_data()
    actuals = data.get("actual_resources", [])
    resources_json = json.dumps(actuals, ensure_ascii=False) if actuals else None

    await update_task_progress(task_id, percent)
    await add_report(task_id, percent, resources_actual=resources_json)

    # ساخت متن منابع برای مدیر
    resources_report = ""
    if actuals:
        resources_report = "\n\n📦 وضعیت منابع:\n"
        for a in actuals:
            resources_report += (
                f"• {a['category']}: {a['planned']}\n"
                f"  برنامه‌ای: {a['planned']}\n"
                f"  موجود (اکچوال): {a['actual']}\n\n"
            )

    user_info = await get_user_info_by_telegram_id(callback.from_user.id)
    name = user_info[0] if user_info else callback.from_user.full_name
    username = user_info[1] if user_info else (callback.from_user.username or "-")
    photo_id = user_info[2] if user_info else None

    planned = task['planned_percent']
    calculated = round(planned * percent / 100, 1)  # مثال: ۲۰٪ پلان × ۶۰٪ اعلام = ۱۲٪
    remaining = planned - percent

    text = (
        f"📊 گزارش پیشرفت\n\n"
        f"👤 مسئول: {name} (@{username})\n"
        f"🆔 تسک #{task_id}: {task['task_name']}\n"
        f"📍 موقعیت: {task['location'] or '-'}\n"
        f"📈 درصد اعلام‌شده: {percent}%\n"
        f"🎯 پلان: {task['planned_percent']}%\n"
        f"🧮 پیشرفت محاسبه‌شده: {calculated}%\n"
        f"📉 باقی‌مانده: {remaining}%\n"
        f"🕐 ساعت: {now_iran().strftime('%H:%M')}"
        f"{resources_report}"
    )
    if calculated < planned:
        text += "\n⚠️ عقب از برنامه"

    if photo_id:
        try:
            await bot.send_photo(ADMIN_ID, photo_id, caption=text)
        except:
            await bot.send_message(ADMIN_ID, text)
    else:
        await bot.send_message(ADMIN_ID, text)

    await state.update_data(pending_task_id=task_id, pending_percent=percent)
    await state.set_state(ReportAttach.waiting_attach)

    await callback.message.answer(
        f"✅ درصد {percent}% ثبت شد.\n\nآیا می‌خواهید متن، عکس، فیلم یا فایل هم پیوست کنید؟",
        reply_markup=yes_no_keyboard("ra_")
    )
    await callback.answer()

@dp.callback_query(ReportAttach.waiting_attach, F.data.in_(["ra_yes", "ra_no"]))
async def report_attach_decision(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    task_id = data.get("pending_task_id")
    if callback.data == "ra_no":
        await state.clear()
        await callback.message.answer(
            "✅ گزارش نهایی شد.",
            reply_markup=report_keyboard(task_id)
        )
    else:
        await callback.message.answer("حالا متن، عکس، فیلم یا فایل را بفرستید:")

@dp.message(ReportAttach.waiting_attach, F.text | F.photo | F.video | F.document)
async def process_report_attach(message: Message, state: FSMContext):
    data = await state.get_data()
    task_id = data.get("pending_task_id")
    percent = data.get("pending_percent", 0)

    text_report = message.caption or message.text
    media_id = None
    if message.photo:
        media_id = message.photo[-1].file_id
    elif message.video:
        media_id = message.video.file_id
    elif message.document:
        media_id = message.document.file_id

    user_info = await get_user_info_by_telegram_id(message.from_user.id)
    name = user_info[0] if user_info else message.from_user.full_name
    username = user_info[1] if user_info else (message.from_user.username or "-")

    header = f"📎 پیوست گزارش از {name} (@{username})\nتسک #{task_id} | درصد {percent}%\n🕐 {now_iran().strftime('%H:%M')}\n\n{text_report or ''}"
    if message.photo:
        await bot.send_photo(ADMIN_ID, media_id, caption=header)
    elif message.video:
        await bot.send_video(ADMIN_ID, media_id, caption=header)
    elif message.document:
        await bot.send_document(ADMIN_ID, media_id, caption=header)
    else:
        await bot.send_message(ADMIN_ID, header)

    await state.clear()
    await message.answer("✅ پیوست ارسال شد.", reply_markup=report_keyboard(task_id))

@dp.callback_query(F.data.startswith("text:"))
async def ask_text(callback: CallbackQuery, state: FSMContext):
    task_id = int(callback.data.split(":")[1])
    await state.update_data(pending_task_id=task_id, pending_percent=0)
    await state.set_state(ReportAttach.waiting_attach)
    await callback.message.answer("متن، عکس، فیلم یا فایل را بفرستید:")
    await callback.answer()

@dp.message(F.text | F.photo | F.video | F.document)
async def handle_media(message: Message, state: FSMContext):
    current = await state.get_state()
    if current:
        return
    if message.from_user.id == ADMIN_ID:
        return
    user_info = await get_user_info_by_telegram_id(message.from_user.id)
    name = user_info[0] if user_info else message.from_user.full_name
    username = user_info[1] if user_info else (message.from_user.username or "-")
    photo_id = user_info[2] if user_info else None
    caption = message.caption or message.text or "بدون توضیح"
    header = f"📎 گزارش آزاد از {name} (@{username})\n🕐 {now_iran().strftime('%H:%M')}\n\n{caption}"
    if photo_id:
        try:
            await bot.send_photo(ADMIN_ID, photo_id, caption=header)
        except:
            await bot.send_message(ADMIN_ID, header)
    else:
        await bot.send_message(ADMIN_ID, header)
    if message.photo:
        await bot.send_photo(ADMIN_ID, message.photo[-1].file_id)
    elif message.video:
        await bot.send_video(ADMIN_ID, message.video.file_id)
    elif message.document:
        await bot.send_document(ADMIN_ID, message.document.file_id)
    await message.answer("✅ ارسال شد.")

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
        await bot.send_message(ADMIN_ID, f"🔴 آلارم\n@{username} تسک «{task_name}» را تأیید نکرد.\nساعت: {send_time}")

# ==================== زمان‌بندی ====================
async def daily_hours_ask():
    while True:
        now = now_iran()
        target = now.replace(hour=5, minute=0, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        await asyncio.sleep((target - now).total_seconds())
        try:
            await bot.send_message(ADMIN_ID, "⏰ ساعت ۵ صبح است.\nساعت کاری امروز را وارد کنید:\n/sethours 08:00 17:00")
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
        await bot.send_message(ADMIN_ID, "گزارش پایان روز: تسکی ثبت نشده.")
        return
    summary = f"📊 گزارش نهایی روز {working_date}\n\n"
    stats = {}
    for task in tasks:
        task_id, name, username = task[0], task['task_name'], task[4]
        planned, actual = task['planned_percent'], task[9] or 0
        if username not in stats:
            stats[username] = 0
        stats[username] += 1
        summary += f"🔹 #{task_id}: {name}\n   @{username} | پلان {planned}% | واقعی {actual}% | باقی {planned - actual}%\n"
    summary += "\n📈 آمار:\n"
    for u, c in stats.items():
        summary += f"• @{u}: {c} تسک\n"
    await bot.send_message(ADMIN_ID, summary)

async def main():
    await init_db()
    asyncio.create_task(daily_hours_ask())
    asyncio.create_task(end_of_day_report())
    print("ربات روشن شد (نسخه کامل با گزارش منابع)...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())