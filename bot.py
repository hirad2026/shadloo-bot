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

class SetPhoto(StatesGroup):
    waiting_photo = State()

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
        clean_resp = data["responsible"].lower().replace("@", "").strip()
        cursor = await db.execute("""
            INSERT INTO tasks (
                date, time, task_name, responsible_username, planned_percent, location,
                resources, sent_at, working_date, attach_file_id, attach_caption
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (
            working_date, now.split()[1], data["task_name"],
            clean_resp, data["planned_percent"], data.get("location"),
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
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM tasks WHERE working_date = ?", (working_date,))
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

# ==================== کمکی ====================
def yes_no_keyboard(prefix=""):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="بله", callback_data=f"{prefix}yes"),
        InlineKeyboardButton(text="خیر", callback_data=f"{prefix}no")
    ]])

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

def calc_remaining(planned: int, actual: int) -> float:
    """باقیمانده = پلان - (پلان × اعلام/۱۰۰)"""
    planned = planned or 0
    actual = actual or 0
    done = planned * actual / 100
    return round(planned - done, 1)

def format_task_line(task) -> str:
    planned = task['planned_percent'] or 0
    actual = task['actual_percent'] or 0
    remaining = calc_remaining(planned, actual)
    calculated = round(planned * actual / 100, 1) if actual else 0
    loc = task['location'] or "-"
    return (
        f"🔹 #{task['id']}: {task['task_name']}\n"
        f"   📍 {loc}\n"
        f"   🎯 پلان: {planned}% | ✅ اعلام: {actual}% | انجام‌شده: {calculated}% | 📉 باقی: {remaining}%\n"
        f"   👤 @{task['responsible_username']} | وضعیت: {task['status'] or '-'}\n"
    )

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

def extract_username(raw: str) -> str:
    possible = re.findall(r'[a-zA-Z0-9_]{3,}', raw)
    if possible:
        return possible[0].lower()
    return raw.lower().replace("@", "").strip().split()[-1]

# ==================== انتقال باقیمانده ====================
async def carry_over_incomplete_tasks(working_date: str):
    tasks = await get_today_tasks(working_date)
    next_date = (datetime.strptime(working_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    carried = 0

    for task in tasks:
        planned = task['planned_percent'] or 0
        actual = task['actual_percent'] or 0
        done = planned * actual / 100
        remaining = round(planned - done, 1)

        if remaining <= 0:
            continue

        new_name = f"{task['task_name']} (باقیمانده از {working_date})"
        resources = task['resources'] or "{}"
        location = task['location'] or ""
        username = task['responsible_username']

        async with aiosqlite.connect(DB_NAME) as db:
            now = now_iran().strftime("%Y-%m-%d %H:%M")
            cursor = await db.execute("""
                INSERT INTO tasks (
                    date, time, task_name, responsible_username, planned_percent,
                    location, resources, sent_at, working_date,
                    carried_from_previous, status
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (
                next_date, now.split()[1], new_name, username, remaining,
                location, resources, now, next_date,
                1, 'از روز قبل'
            ))
            await db.commit()
            new_id = cursor.lastrowid

        tg_id = await get_telegram_id_by_username(username)
        if tg_id:
            text = (
                f"📋 تسک باقیمانده از روز قبل\n\n"
                f"🕐 {now.split()[1]}\n"
                f"🆔 #{new_id}\n"
                f"📝 {new_name}\n"
                f"📍 موقعیت: {location or 'ثبت نشده'}\n"
                f"📊 پلان باقیمانده: {remaining}%\n"
                f"(پلان روز قبل: {planned}% | اعلام مسئول: {actual}% | انجام‌شده: {done}%)\n\n"
                f"⚠️ این تسک به‌صورت خودکار از روز قبل منتقل شده است."
            )
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ تأیید دریافت", callback_data=f"confirm:{new_id}")],
                [InlineKeyboardButton(text="📊 گزارش پیشرفت", callback_data=f"report:{new_id}")]
            ])
            try:
                await bot.send_message(tg_id, text, reply_markup=kb)
                carried += 1
            except:
                pass

    return carried

# ==================== دستورات پایه ====================
@dp.message(Command("start"))
async def cmd_start(message: Message):
    user = message.from_user
    await add_or_update_user(username=user.username, full_name=user.full_name, telegram_id=user.id)
    if user.id == ADMIN_ID:
        await message.answer("سلام آقای شادلو\nربات آماده است.\n\nبرای دیدن همه دستورات بزن:\n/help")
    else:
        await message.answer("شما به عنوان مسئول ثبت شدید.\nمنتظر تسک‌ها باشید.")

@dp.message(Command("help"))
async def cmd_help(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("دستورات مسئول:\n/start")
        return
    await message.answer(
        "📖 راهنمای دستورات مدیر\n\n"
        "─── تسک ───\n"
        "/newtask → ثبت تسک جدید\n"
        "/tasks today → تسک‌های امروز\n"
        "/tasks week → تسک‌های این هفته\n"
        "/tasks month → تسک‌های این ماه\n"
        "/carryover → انتقال دستی باقیمانده‌ها به فردا\n\n"
        "─── مسئولین ───\n"
        "/adduser نام یوزرنیم → افزودن مسئول (+ عکس)\n"
        "/setphoto یوزرنیم → تعویض/افزودن عکس\n"
        "/users → لیست مسئولین\n"
        "/team → پوشه مسئولین\n"
        "/link یوزرنیم آیدی\n"
        "/deluser یوزرنیم\n"
        "/fixusernames → اصلاح یوزرنیم‌های خراب\n\n"
        "─── ساعت کاری ───\n"
        "/sethours 08:00 17:00\n\n"
        "عکس مسئول همراه گزارش‌ها ارسال می‌شود."
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
    await update_user_photo(data.get("pending_username"), message.photo[-1].file_id)
    await state.clear()
    await message.answer("✅ عکس مسئول ذخیره شد.")

@dp.message(AddUser.waiting_photo, F.text)
async def process_user_photo_skip(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("عکس ذخیره نشد.")

@dp.message(Command("setphoto"))
async def cmd_setphoto(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        username = message.text.split(maxsplit=1)[1].replace("@", "").lower().strip()
        if not await get_user_by_username(username):
            await message.answer("این یوزرنیم وجود ندارد. اول /adduser بزنید.")
            return
        await state.update_data(pending_username=username)
        await state.set_state(SetPhoto.waiting_photo)
        await message.answer(f"عکس جدید برای @{username} را بفرستید:")
    except:
        await message.answer("فرمت: /setphoto یوزرنیم")

@dp.message(SetPhoto.waiting_photo, F.photo)
async def process_set_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    await update_user_photo(data.get("pending_username"), message.photo[-1].file_id)
    await state.clear()
    await message.answer(f"✅ عکس به‌روز شد.")

@dp.message(SetPhoto.waiting_photo, F.text)
async def process_set_photo_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("لغو شد.")

@dp.message(Command("users"))
async def cmd_users(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    users = await get_all_users()
    text = "لیست مسئولین:\n\n"
    for u in users:
        photo_status = "📷 دارد" if u[3] else "بدون عکس"
        text += f"• {u[0]} → @{u[1]} | ID: {u[2]} | {photo_status}\n"
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
        await message.answer(f"✅ @{username} وصل شد.")
    except Exception as e:
        await message.answer(f"فرمت: /link irancivil2023 6384495297\n{e}")

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

@dp.message(Command("fixusernames"))
async def cmd_fixusernames(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT id, responsible_username FROM tasks")
        rows = await cursor.fetchall()
        fixed = 0
        for task_id, raw in rows:
            if not raw:
                continue
            clean = extract_username(raw)
            if clean != raw.lower():
                await db.execute("UPDATE tasks SET responsible_username = ? WHERE id = ?", (clean, task_id))
                fixed += 1
        await db.commit()
    await message.answer(f"✅ {fixed} تسک اصلاح شد.")

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

@dp.message(Command("carryover"))
async def cmd_carryover(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    today = now_iran().strftime("%Y-%m-%d")
    count = await carry_over_incomplete_tasks(today)
    await message.answer(f"✅ تعداد {count} تسک باقیمانده به فردا منتقل و برای مسئولین ارسال شد.")

# ==================== /team و /tasks ====================
@dp.message(Command("team"))
async def cmd_team(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    users = await get_all_users()
    if not users:
        await message.answer("هیچ مسئولی ثبت نشده.")
        return
    buttons = [[InlineKeyboardButton(text=f"{u[0]} (@{u[1]})", callback_data=f"teamuser:{u[1]}")] for u in users]
    await message.answer("👷 لیست مسئولین:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

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
    text = f"👤 {full_name} (@{uname})\n📅 امروز ({today})\nتعداد تسک: {len(tasks)}\n\n"
    if not tasks:
        text += "تسکی برای امروز نیست.\n(در صورت نیاز /fixusernames بزنید)"
    else:
        for t in tasks:
            text += format_task_line(t) + "\n"
        reports = await get_reports_by_task_ids([t['id'] for t in tasks])
        if reports:
            text += "\n📝 آخرین گزارش‌ها:\n"
            for r in reports[:10]:
                text += f"• تسک #{r['task_id']} | {r['reported_percent']}% | {r['created_at']}\n"
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="امروز", callback_data=f"userperiod:{username}:today"),
        InlineKeyboardButton(text="این هفته", callback_data=f"userperiod:{username}:week"),
        InlineKeyboardButton(text="این ماه", callback_data=f"userperiod:{username}:month"),
    ], [InlineKeyboardButton(text="🔙 بازگشت به تیم", callback_data="back_team")]])
    if photo_id:
        try:
            await bot.send_photo(ADMIN_ID, photo_id, caption=text[:1024], reply_markup=kb)
            if len(text) > 1024:
                await bot.send_message(ADMIN_ID, text[1024:])
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
    else:
        start = today.replace(day=1).strftime("%Y-%m-%d")
        end = today.strftime("%Y-%m-%d")
        title = "این ماه"
    user = await get_user_by_username(username)
    full_name = user[0] if user else username
    tasks = await get_tasks_by_username(username, start, end)
    text = f"👤 {full_name} (@{username})\n📅 {title}\nتعداد: {len(tasks)}\n\n"
    if not tasks:
        text += "تسکی یافت نشد."
    else:
        for t in tasks:
            text += format_task_line(t) + "\n"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 بازگشت به تیم", callback_data="back_team")]])
    await callback.message.answer(text, reply_markup=kb)

@dp.callback_query(F.data == "back_team")
async def back_to_team(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.answer()
    users = await get_all_users()
    if not users:
        await callback.message.answer("هیچ مسئولی ثبت نشده.")
        return
    buttons = [[InlineKeyboardButton(text=f"{u[0]} (@{u[1]})", callback_data=f"teamuser:{u[1]}")] for u in users]
    await callback.message.answer("👷 لیست مسئولین:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

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
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="امروز", callback_data="tasksperiod:today"),
        InlineKeyboardButton(text="این هفته", callback_data="tasksperiod:week"),
        InlineKeyboardButton(text="این ماه", callback_data="tasksperiod:month"),
    ], [InlineKeyboardButton(text="👷 لیست مسئولین", callback_data="back_team")]])
    if len(text) > 4000:
        for i in range(0, len(text), 4000):
            await message.answer(text[i:i+4000], reply_markup=kb if i+4000 >= len(text) else None)
    else:
        await message.answer(text, reply_markup=kb)

@dp.callback_query(F.data.startswith("tasksperiod:"))
async def process_tasks_period(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    period = callback.data.split(":")[1]
    await callback.answer()
    today = now_iran().date()
    if period == "today":
        start = end = today.strftime("%Y-%m-%d")
        title = "امروز"
    elif period == "week":
        start = (today - timedelta(days=today.weekday())).strftime("%Y-%m-%d")
        end = today.strftime("%Y-%m-%d")
        title = "این هفته"
    else:
        start = today.replace(day=1).strftime("%Y-%m-%d")
        end = today.strftime("%Y-%m-%d")
        title = "این ماه"
    tasks = await get_tasks_by_date_range(start, end)
    text = f"📋 تسک‌های {title}\nتعداد: {len(tasks)}\n\n"
    if not tasks:
        text += "تسکی ثبت نشده."
    else:
        for t in tasks:
            text += format_task_line(t) + "\n"
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="امروز", callback_data="tasksperiod:today"),
        InlineKeyboardButton(text="این هفته", callback_data="tasksperiod:week"),
        InlineKeyboardButton(text="این ماه", callback_data="tasksperiod:month"),
    ], [InlineKeyboardButton(text="👷 لیست مسئولین", callback_data="back_team")]])
    await callback.message.answer(text, reply_markup=kb)

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
    await message.answer("📊 درصد پیشرفت برنامه‌ای (فقط عدد):")

@dp.message(NewTask.planned_percent)
async def process_percent_input(message: Message, state: FSMContext):
    try:
        await state.update_data(planned_percent=int(message.text.strip()))
        await state.set_state(NewTask.location)
        await message.answer("📍 موقعیت این تسک کجاست؟")
    except:
        await message.answer("فقط عدد وارد کنید.")

@dp.message(NewTask.location)
async def process_location(message: Message, state: FSMContext):
    await state.update_data(location=message.text.strip())
    await state.set_state(NewTask.responsible)
    await message.answer("👤 نام و یوزرنیم مسئول:\nمثال: علی رضایی @ali_rezaei")

@dp.message(NewTask.responsible)
async def process_responsible(message: Message, state: FSMContext):
    await state.update_data(responsible=message.text.strip())
    await state.update_data(resources={"manpower": [], "materials": [], "machines": [], "tools": []})
    await state.set_state(NewTask.manpower_item)
    await message.answer("👷 نیروی انسانی:\nمثال: استادکار بنا ۴ نفر")

@dp.message(NewTask.manpower_item)
async def process_manpower(message: Message, state: FSMContext):
    data = await state.get_data()
    data["resources"]["manpower"].append(message.text.strip())
    await state.update_data(resources=data["resources"])
    await state.set_state(NewTask.manpower_more)
    await message.answer("آیا نیروی انسانی دیگری نیاز است؟", reply_markup=yes_no_keyboard("mp_"))

@dp.callback_query(NewTask.manpower_more, F.data.in_(["mp_yes", "mp_no"]))
async def manpower_more(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if callback.data == "mp_yes":
        await state.set_state(NewTask.manpower_item)
        await callback.message.answer("👷 نیروی انسانی بعدی:")
    else:
        await state.set_state(NewTask.material_item)
        await callback.message.answer("🧱 مصالح:\nمثال: سیمان ۵۰ کیسه")

@dp.message(NewTask.material_item)
async def process_material(message: Message, state: FSMContext):
    data = await state.get_data()
    data["resources"]["materials"].append(message.text.strip())
    await state.update_data(resources=data["resources"])
    await state.set_state(NewTask.material_more)
    await message.answer("آیا مصالح دیگری نیاز است؟", reply_markup=yes_no_keyboard("mt_"))

@dp.callback_query(NewTask.material_more, F.data.in_(["mt_yes", "mt_no"]))
async def material_more(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if callback.data == "mt_yes":
        await state.set_state(NewTask.material_item)
        await callback.message.answer("🧱 مصالح بعدی:")
    else:
        await state.set_state(NewTask.machine_item)
        await callback.message.answer("🚜 ماشین‌آلات:\nمثال: بیل مکانیکی ۱ دستگاه - ۸ ساعت")

@dp.message(NewTask.machine_item)
async def process_machine(message: Message, state: FSMContext):
    data = await state.get_data()
    data["resources"]["machines"].append(message.text.strip())
    await state.update_data(resources=data["resources"])
    await state.set_state(NewTask.machine_more)
    await message.answer("آیا ماشین‌آلات دیگری نیاز است؟", reply_markup=yes_no_keyboard("mc_"))

@dp.callback_query(NewTask.machine_more, F.data.in_(["mc_yes", "mc_no"]))
async def machine_more(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if callback.data == "mc_yes":
        await state.set_state(NewTask.machine_item)
        await callback.message.answer("🚜 ماشین‌آلات بعدی:")
    else:
        await state.set_state(NewTask.tool_item)
        await callback.message.answer("🔧 ابزارآلات:\nمثال: چکش برقی ۳ عدد")

@dp.message(NewTask.tool_item)
async def process_tool(message: Message, state: FSMContext):
    data = await state.get_data()
    data["resources"]["tools"].append(message.text.strip())
    await state.update_data(resources=data["resources"])
    await state.set_state(NewTask.tool_more)
    await message.answer("آیا ابزارآلات دیگری نیاز است؟", reply_markup=yes_no_keyboard("tl_"))

@dp.callback_query(NewTask.tool_more, F.data.in_(["tl_yes", "tl_no"]))
async def tool_more(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if callback.data == "tl_yes":
        await state.set_state(NewTask.tool_item)
        await callback.message.answer("🔧 ابزارآلات بعدی:")
    else:
        await state.set_state(NewTask.attach_ask)
        await callback.message.answer("📎 مشخصات فنی / کروکی پیوست می‌کنید؟", reply_markup=yes_no_keyboard("at_"))

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
    file_id = message.document.file_id if message.document else (message.photo[-1].file_id if message.photo else message.video.file_id)
    await state.update_data(attach_file_id=file_id)
    await state.set_state(NewTask.attach_caption)
    await message.answer("توضیح کوتاه (یا «ندارد»):")

@dp.message(NewTask.attach_caption)
async def process_attach_caption(message: Message, state: FSMContext):
    caption = None if message.text.strip() == "ندارد" else message.text.strip()
    await state.update_data(attach_caption=caption)
    await finish_task(message, state)

async def finish_task(message: Message, state: FSMContext):
    data = await state.get_data()
    clean_username = extract_username(data["responsible"])
    data["responsible"] = clean_username
    task_id = await add_task_full(data)
    await state.clear()

    res = data.get("resources", {})
    resources_text = ""
    for key, title in [("manpower", "👷 نیروی انسانی"), ("materials", "🧱 مصالح"), ("machines", "🚜 ماشین‌آلات"), ("tools", "🔧 ابزارآلات")]:
        if res.get(key):
            resources_text += f"{title}:\n" + "\n".join(f"• {x}" for x in res[key]) + "\n\n"

    send_time = now_iran().strftime("%H:%M")
    tg_id = await get_telegram_id_by_username(clean_username)
    text = (
        f"📋 تسک جدید\n\n🕐 {send_time}\n🆔 #{task_id}\n📝 {data['task_name']}\n"
        f"📍 {data.get('location', '-')}\n📊 پلان: {data['planned_percent']}%\n\n{resources_text}"
    )
    if tg_id:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ تأیید دریافت", callback_data=f"confirm:{task_id}")],
            [InlineKeyboardButton(text="📊 گزارش پیشرفت", callback_data=f"report:{task_id}")]
        ])
        await bot.send_message(tg_id, text, reply_markup=kb)
        if data.get("attach_file_id"):
            try:
                await bot.send_document(tg_id, data["attach_file_id"], caption=data.get("attach_caption") or "پیوست")
            except:
                try:
                    await bot.send_photo(tg_id, data["attach_file_id"], caption=data.get("attach_caption") or "پیوست")
                except:
                    pass
        user_info = await get_user_by_username(clean_username)
        resp_name = user_info[0] if user_info else clean_username
        await message.answer(f"✅ تسک #{task_id} ارسال شد برای:\n👤 {resp_name}\n@{clean_username}")
        asyncio.create_task(reminder_and_alarm(task_id, tg_id, clean_username, data["task_name"], send_time))
    else:
        await message.answer(f"✅ تسک #{task_id} ثبت شد ولی آیدی @{clean_username} پیدا نشد.")

# ==================== گزارش مسئول ====================
@dp.callback_query(F.data.startswith("confirm:"))
async def process_confirm(callback: CallbackQuery, state: FSMContext):
    task_id = int(callback.data.split(":")[1])
    await mark_confirmed(task_id)
    try:
        await callback.message.edit_text(callback.message.text + f"\n\n✅ دریافت در {now_iran().strftime('%H:%M')} تأیید شد.")
    except:
        pass
    await callback.answer("تأیید شد.")
    await start_resource_report(callback, state, task_id)

@dp.callback_query(F.data.startswith("report:"))
async def start_report(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await start_resource_report(callback, state, int(callback.data.split(":")[1]))

async def start_resource_report(callback: CallbackQuery, state: FSMContext, task_id: int):
    task = await get_task(task_id)
    if not task:
        await callback.message.answer("تسک پیدا نشد.")
        return
    try:
        resources = json.loads(task['resources'] or "{}")
        if not isinstance(resources, dict):
            resources = {}
    except:
        resources = {}
    items = build_resource_list(resources)
    if not items:
        expected = await get_expected_percent(task['planned_percent'])
        await callback.message.answer(
            f"📊 گزارش #{task_id}\n📝 {task['task_name']}\n📍 {task['location'] or '-'}\n"
            f"🎯 پلان: {task['planned_percent']}%\n⏰ {expected}\n\nدرصد را انتخاب کنید:",
            reply_markup=report_keyboard(task_id)
        )
        return
    await state.set_state(ResourceReport.waiting_resource)
    await state.update_data(report_task_id=task_id, resource_items=items, resource_index=0, actual_resources=[])
    cat, planned_val = items[0]
    await callback.message.answer(
        f"📋 گزارش منابع تسک #{task_id}\n\nدسته: {cat}\nبرنامه‌ای: {planned_val}\n\n❓ مقدار موجود (اکچوال) را بنویسید:"
    )

@dp.message(ResourceReport.waiting_resource)
async def process_resource_actual(message: Message, state: FSMContext):
    data = await state.get_data()
    items = data["resource_items"]
    index = data["resource_index"]
    actuals = data.get("actual_resources", [])
    cat, planned_val = items[index]
    actuals.append({"category": cat, "planned": planned_val, "actual": message.text.strip()})
    index += 1
    await state.update_data(resource_index=index, actual_resources=actuals)
    if index < len(items):
        cat, planned_val = items[index]
        await message.answer(f"دسته: {cat}\nبرنامه‌ای: {planned_val}\n\n❓ مقدار موجود را بنویسید:")
    else:
        task = await get_task(data["report_task_id"])
        expected = await get_expected_percent(task['planned_percent'])
        await state.set_state(ResourceReport.waiting_percent)
        await message.answer(
            f"✅ منابع تمام شد.\n\n📊 درصد پیشرفت فعلی را انتخاب کنید:\n🎯 پلان: {task['planned_percent']}%\n⏰ {expected}",
            reply_markup=report_keyboard(data["report_task_id"])
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
    await update_task_progress(task_id, percent)
    await add_report(task_id, percent, resources_actual=json.dumps(actuals, ensure_ascii=False) if actuals else None)

    resources_report = ""
    if actuals:
        resources_report = "\n\n📦 وضعیت منابع:\n"
        for a in actuals:
            resources_report += f"• {a['category']}: {a['planned']}\n  برنامه‌ای: {a['planned']}\n  موجود: {a['actual']}\n\n"

    user_info = await get_user_info_by_telegram_id(callback.from_user.id)
    name = user_info[0] if user_info else callback.from_user.full_name
    username = user_info[1] if user_info else (callback.from_user.username or "-")
    photo_id = user_info[2] if user_info else None

    planned = task['planned_percent']
    calculated = round(planned * percent / 100, 1)
    remaining = calc_remaining(planned, percent)

    text = (
        f"📊 گزارش پیشرفت\n\n👤 {name} (@{username})\n"
        f"🆔 #{task_id}: {task['task_name']}\n📍 {task['location'] or '-'}\n"
        f"📈 اعلام: {percent}%\n🎯 پلان: {planned}%\n"
        f"🧮 انجام‌شده: {calculated}%\n📉 باقی: {remaining}%\n"
        f"🕐 {now_iran().strftime('%H:%M')}{resources_report}"
    )
    if remaining > 0:
        text += "\n⚠️ عقب از برنامه"

    if photo_id:
        try:
            await bot.send_photo(ADMIN_ID, photo_id, caption=text)
        except:
            await bot.send_message(ADMIN_ID, text)
    else:
        await bot.send_message(ADMIN_ID, text + "\n(عکس ثبت نشده — /setphoto)")

    await state.update_data(pending_task_id=task_id, pending_percent=percent)
    await state.set_state(ReportAttach.waiting_attach)
    await callback.message.answer(f"✅ {percent}% ثبت شد.\nپیوست می‌خواهید؟", reply_markup=yes_no_keyboard("ra_"))
    await callback.answer()

@dp.callback_query(ReportAttach.waiting_attach, F.data.in_(["ra_yes", "ra_no"]))
async def report_attach_decision(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    task_id = data.get("pending_task_id")
    if callback.data == "ra_no":
        await state.clear()
        await callback.message.answer("✅ گزارش نهایی شد.", reply_markup=report_keyboard(task_id))
    else:
        await callback.message.answer("متن، عکس، فیلم یا فایل را بفرستید:")

@dp.message(ReportAttach.waiting_attach, F.text | F.photo | F.video | F.document)
async def process_report_attach(message: Message, state: FSMContext):
    data = await state.get_data()
    task_id = data.get("pending_task_id")
    percent = data.get("pending_percent", 0)
    text_report = message.caption or message.text
    media_id = message.photo[-1].file_id if message.photo else (message.video.file_id if message.video else (message.document.file_id if message.document else None))
    user_info = await get_user_info_by_telegram_id(message.from_user.id)
    name = user_info[0] if user_info else message.from_user.full_name
    username = user_info[1] if user_info else (message.from_user.username or "-")
    header = f"📎 پیوست از {name} (@{username})\nتسک #{task_id} | {percent}%\n🕐 {now_iran().strftime('%H:%M')}\n\n{text_report or ''}"
    if message.photo:
        await bot.send_photo(ADMIN_ID, media_id, caption=header)
    elif message.video:
        await bot.send_video(ADMIN_ID, media_id, caption=header)
    elif message.document:
        await bot.send_document(ADMIN_ID, media_id, caption=header)
    else:
        await bot.send_message(ADMIN_ID, header)
    await state.clear()
    await message.answer("✅ ارسال شد.", reply_markup=report_keyboard(task_id))

@dp.callback_query(F.data.startswith("text:"))
async def ask_text(callback: CallbackQuery, state: FSMContext):
    await state.update_data(pending_task_id=int(callback.data.split(":")[1]), pending_percent=0)
    await state.set_state(ReportAttach.waiting_attach)
    await callback.message.answer("متن، عکس، فیلم یا فایل را بفرستید:")
    await callback.answer()

@dp.message(F.text | F.photo | F.video | F.document)
async def handle_media(message: Message, state: FSMContext):
    if await state.get_state() or message.from_user.id == ADMIN_ID:
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

async def daily_hours_ask():
    while True:
        now = now_iran()
        target = now.replace(hour=5, minute=0, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        await asyncio.sleep((target - now).total_seconds())
        try:
            await bot.send_message(ADMIN_ID, "⏰ ساعت ۵ صبح.\n/sethours 08:00 17:00")
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
            report_time = now.replace(hour=h, minute=m, second=0, microsecond=0) + timedelta(minutes=30)
            if now >= report_time and now < report_time + timedelta(minutes=1):
                await send_daily_summary(hours_date)
        except:
            pass

async def send_daily_summary(working_date: str):
    carried_count = await carry_over_incomplete_tasks(working_date)
    tasks = await get_today_tasks(working_date)
    if not tasks:
        await bot.send_message(ADMIN_ID, f"گزارش پایان روز {working_date}: تسکی نبود.\nمنتقل‌شده: {carried_count}")
        return
    summary = f"📊 گزارش نهایی روز {working_date}\n\n"
    stats = {}
    for task in tasks:
        planned = task['planned_percent'] or 0
        actual = task['actual_percent'] or 0
        remaining = calc_remaining(planned, actual)
        calculated = round(planned * actual / 100, 1)
        username = task['responsible_username']
        stats[username] = stats.get(username, 0) + 1
        summary += (
            f"🔹 #{task['id']}: {task['task_name']}\n"
            f"   @{username} | پلان {planned}% | اعلام {actual}% | انجام {calculated}% | باقی {remaining}%\n"
        )
    summary += f"\n🔄 منتقل‌شده به فردا: {carried_count}\n\n📈 آمار:\n"
    for u, c in stats.items():
        summary += f"• @{u}: {c} تسک\n"
    await bot.send_message(ADMIN_ID, summary)

async def main():
    await init_db()
    asyncio.create_task(daily_hours_ask())
    asyncio.create_task(end_of_day_report())
    print("ربات روشن شد (نسخه کامل + carryover)...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())