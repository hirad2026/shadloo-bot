import asyncio
import logging
import aiosqlite
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
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
        except: pass

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
            except: pass

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

async def add_or_update_user(username=None, full_name=None, telegram_id=None, photo_file_id=None):
    async with aiosqlite.connect(DB_NAME) as db:
        clean_username = (username or "").lower().replace("@", "").strip() if username else None

        if telegram_id:
            # اول با telegram_id پیدا کن
            cursor = await db.execute("SELECT id, username FROM users WHERE telegram_id = ?", (telegram_id,))
            row = await cursor.fetchone()
            if row:
                # آپدیت
                await db.execute("""
                    UPDATE users SET 
                        full_name = COALESCE(?, full_name),
                        username = COALESCE(?, username),
                        photo_file_id = COALESCE(?, photo_file_id)
                    WHERE telegram_id = ?
                """, (full_name, clean_username, photo_file_id, telegram_id))
            else:
                # اگر با یوزرنیم از قبل وجود دارد
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
                        await db.execute("""
                            INSERT INTO users (full_name, username, telegram_id, photo_file_id)
                            VALUES (?, ?, ?, ?)
                        """, (full_name or "نامشخص", clean_username, telegram_id, photo_file_id))
                else:
                    await db.execute("""
                        INSERT INTO users (full_name, username, telegram_id, photo_file_id)
                        VALUES (?, ?, ?, ?)
                    """, (full_name or "نامشخص", "", telegram_id, photo_file_id))
        await db.commit()

async def get_telegram_id_by_username(username: str):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT telegram_id FROM users WHERE username=?", (username.lower().replace("@",""),))
        row = await cursor.fetchone()
        return row[0] if row else None

async def get_user_info_by_telegram_id(telegram_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT full_name, username, photo_file_id FROM users WHERE telegram_id=?", (telegram_id,))
        return await cursor.fetchone()

async def get_user_by_username(username: str):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT full_name, username, photo_file_id, telegram_id FROM users WHERE username=?", (username.lower().replace("@",""),))
        return await cursor.fetchone()

async def add_user(full_name: str, username: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR IGNORE INTO users (full_name, username) VALUES (?,?)", (full_name, username.lower().replace("@","")))
        await db.commit()

async def update_user_photo(username: str, photo_file_id: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET photo_file_id=? WHERE username=?", (photo_file_id, username.lower().replace("@","")))
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
            INSERT INTO tasks (date, time, task_name, responsible_username, planned_percent, location,
                               resources, sent_at, working_date, attach_file_id, attach_caption)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (
            working_date, now.split()[1], data["task_name"],
            data["responsible"].lower().replace("@",""),
            data["planned_percent"], data.get("location"),
            resources_json, now, working_date,
            data.get("attach_file_id"), data.get("attach_caption")
        ))
        await db.commit()
        return cursor.lastrowid

async def get_task(task_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT * FROM tasks WHERE id=?", (task_id,))
        return await cursor.fetchone()

async def mark_confirmed(task_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE tasks SET confirmed=1 WHERE id=?", (task_id,))
        await db.commit()

async def is_confirmed(task_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT confirmed FROM tasks WHERE id=?", (task_id,))
        row = await cursor.fetchone()
        return row[0] == 1 if row else False

async def update_task_progress(task_id: int, actual_percent: int):
    async with aiosqlite.connect(DB_NAME) as db:
        now = now_iran().strftime("%Y-%m-%d %H:%M")
        await db.execute("UPDATE tasks SET actual_percent=?, last_report=?, status='در حال انجام' WHERE id=?", (actual_percent, now, task_id))
        await db.commit()

async def add_report(task_id: int, reported_percent: int, text_report=None, media_file_id=None):
    async with aiosqlite.connect(DB_NAME) as db:
        now = now_iran().strftime("%Y-%m-%d %H:%M")
        await db.execute("INSERT INTO reports (task_id, reported_percent, text_report, media_file_id, created_at) VALUES (?,?,?,?,?)",
                         (task_id, reported_percent, text_report, media_file_id, now))
        await db.commit()

async def get_today_tasks(working_date: str):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT * FROM tasks WHERE working_date=?", (working_date,))
        return await cursor.fetchall()

async def get_reports_for_task(task_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT * FROM reports WHERE task_id=? ORDER BY created_at", (task_id,))
        return await cursor.fetchall()

# ==================== کیبوردها ====================
def yes_no_keyboard(prefix=""):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="بله", callback_data=f"{prefix}yes"),
         InlineKeyboardButton(text="خیر", callback_data=f"{prefix}no")]
    ])

def report_keyboard(task_id: int):
    buttons = []
    row = []
    for p in [10,20,30,40,50,60,70,80,90,100]:
        row.append(InlineKeyboardButton(text=f"{p}%", callback_data=f"prog:{task_id}:{p}"))
        if len(row) == 5:
            buttons.append(row)
            row = []
    if row: buttons.append(row)
    buttons.append([InlineKeyboardButton(text="📝 فقط متن/عکس/فیلم", callback_data=f"text:{task_id}")])
    buttons.append([InlineKeyboardButton(text="🔄 گزارش مجدد", callback_data=f"report:{task_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ==================== دستورات پایه ====================
@dp.message(Command("start"))
async def cmd_start(message: Message):
    user = message.from_user
    username = user.username.lower() if user.username else None
    full_name = user.full_name or "نامشخص"

    await add_or_update_user(
        username=username,
        full_name=full_name,
        telegram_id=user.id
    )

    if user.id == ADMIN_ID:
        await message.answer(
            "سلام آقای شادلو\nربات آماده است.\n\n"
            "/newtask → ثبت تسک جدید\n"
            "/adduser نام یوزرنیم\n"
            "/users\n"
            "/sethours 08:00 17:00"
        )
    else:
        await message.answer("شما به عنوان مسئول ثبت شدید.\nمنتظر تسک‌ها باشید.")

@dp.message(Command("adduser"))
async def cmd_adduser(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    try:
        parts = message.text.split(maxsplit=2)
        full_name, username = parts[1], parts[2]
        await add_user(full_name, username)
        await state.update_data(pending_username=username.lower().replace("@",""))
        await state.set_state(AddUser.waiting_photo)
        await message.answer(f"✅ {full_name} اضافه شد.\nحالا عکس مسئول را بفرستید (یا بنویسید «ندارد»):")
    except:
        await message.answer("فرمت: /adduser نام یوزرنیم")

@dp.message(AddUser.waiting_photo, F.photo)
async def process_user_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    username = data.get("pending_username")
    photo_id = message.photo[-1].file_id
    await update_user_photo(username, photo_id)
    await state.clear()
    await message.answer("✅ عکس مسئول ذخیره شد.")

@dp.message(AddUser.waiting_photo, F.text)
async def process_user_photo_skip(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("عکس ذخیره نشد. مسئول بدون عکس ثبت شد.")

@dp.message(Command("users"))
async def cmd_users(message: Message):
    if message.from_user.id != ADMIN_ID: return
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
            await db.execute(
                "UPDATE users SET telegram_id = ? WHERE username = ?",
                (telegram_id, username)
            )
            await db.commit()
        
        await message.answer(f"✅ یوزرنیم @{username} به آیدی {telegram_id} وصل شد.")
    except Exception as e:
        await message.answer(f"فرمت درست:\n/link irancivil2023 6384495297\n\nخطا: {e}")

@dp.message(Command("sethours"))
async def cmd_sethours(message: Message):
    if message.from_user.id != ADMIN_ID: return
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
    if message.from_user.id != ADMIN_ID: return
    await state.clear()
    await state.set_state(NewTask.task_name)
    await message.answer("📝 نام فعالیت مورد نظرتان چیست؟")

@dp.message(NewTask.task_name)
async def process_task_name(message: Message, state: FSMContext):
    await state.update_data(task_name=message.text.strip())
    await state.set_state(NewTask.planned_percent)
    await message.answer("📊 درصد پیشرفت برنامه‌ای را وارد کنید (فقط عدد):")

@dp.message(NewTask.planned_percent)
async def process_percent(message: Message, state: FSMContext):
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

# ----- نیروی انسانی -----
@dp.message(NewTask.manpower_item)
async def process_manpower(message: Message, state: FSMContext):
    data = await state.get_data()
    resources = data["resources"]
    resources["manpower"].append(message.text.strip())
    await state.update_data(resources=resources)
    await state.set_state(NewTask.manpower_more)
    await message.answer("آیا نیروی انسانی دیگری نیاز است؟", reply_markup=yes_no_keyboard("mp_"))

@dp.callback_query(NewTask.manpower_more, F.data.in_(["mp_yes", "mp_no"]))
async def manpower_more(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if callback.data == "mp_yes":
        await state.set_state(NewTask.manpower_item)
        await callback.message.answer("👷 نیروی انسانی بعدی را بنویسید:")
    else:
        await state.set_state(NewTask.material_item)
        await callback.message.answer("🧱 مصالح مورد نیاز:\nنوع + مقدار + واحد\nمثال: سیمان ۵۰ کیسه")

# ----- مصالح -----
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

# ----- ماشین‌آلات -----
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

# ----- ابزارآلات -----
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
        await callback.message.answer("📎 آیا مشخصات فنی / کروکی / آیین‌نامه پیوست می‌کنید؟", reply_markup=yes_no_keyboard("at_"))

# ----- فایل پیوست تسک -----
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
    await message.answer("توضیح کوتاه برای فایل بنویسید (یا «ندارد»):")

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
        resources_text += "👷 نیروی انسانی:\n" + "\n".join(f"• {x}" for x in res["manpower"]) + "\n\n"
    if res.get("materials"):
        resources_text += "🧱 مصالح:\n" + "\n".join(f"• {x}" for x in res["materials"]) + "\n\n"
    if res.get("machines"):
        resources_text += "🚜 ماشین‌آلات:\n" + "\n".join(f"• {x}" for x in res["machines"]) + "\n\n"
    if res.get("tools"):
        resources_text += "🔧 ابزارآلات:\n" + "\n".join(f"• {x}" for x in res["tools"]) + "\n\n"

    send_time = now_iran().strftime("%H:%M")

    # ===== استخراج یوزرنیم (حتماً با تورفتگی) =====
    raw = data["responsible"].strip()
    if "@" in raw:
        username = raw.split("@")[-1].strip().lower()
    else:
        username = raw.split()[-1].strip().lower()

    tg_id = await get_telegram_id_by_username(username)

    if not tg_id:
        tg_id = await get_telegram_id_by_username(raw.replace("@", "").strip().lower())
    # ================================================

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

        await message.answer(f"✅ تسک #{task_id} ثبت و برای مسئول ارسال شد.")
        asyncio.create_task(reminder_and_alarm(task_id, tg_id, username, data["task_name"], send_time))
    else:
        await message.answer(f"✅ تسک #{task_id} ثبت شد ولی آیدی مسئول پیدا نشد. او باید /start کند.")

# ==================== گزارش مسئول ====================
@dp.callback_query(F.data.startswith("confirm:"))
async def process_confirm(callback: CallbackQuery):
    task_id = int(callback.data.split(":")[1])
    await mark_confirmed(task_id)
    confirm_time = now_iran().strftime("%H:%M")
    await callback.message.edit_text(callback.message.text + f"\n\n✅ دریافت در ساعت {confirm_time} تأیید شد.")
    task = await get_task(task_id)
    if task:
        await callback.message.answer(
            f"📊 گزارش پیشرفت تسک #{task_id}\n📝 {task[3]}\n📍 {task[6] or 'موقعیت ثبت نشده'}\nپلان: {task[5]}%\n\nهر ساعت می‌توانید گزارش دهید:",
            reply_markup=report_keyboard(task_id)
        )
    await callback.answer("تأیید شد.")

@dp.callback_query(F.data.startswith("report:"))
async def start_report(callback: CallbackQuery):
    task_id = int(callback.data.split(":")[1])
    task = await get_task(task_id)
    if not task:
        await callback.answer("تسک پیدا نشد", show_alert=True)
        return
    resources_text = ""
    try:
        res = json.loads(task[7] or "{}")
        if res.get("manpower"): resources_text += "👷 نیروی انسانی:\n" + "\n".join(f"• {x}" for x in res["manpower"]) + "\n"
        if res.get("materials"): resources_text += "🧱 مصالح:\n" + "\n".join(f"• {x}" for x in res["materials"]) + "\n"
        if res.get("machines"): resources_text += "🚜 ماشین‌آلات:\n" + "\n".join(f"• {x}" for x in res["machines"]) + "\n"
        if res.get("tools"): resources_text += "🔧 ابزارآلات:\n" + "\n".join(f"• {x}" for x in res["tools"]) + "\n"
    except: pass
    await callback.message.answer(
        f"📊 گزارش تسک #{task_id}\n📝 {task[3]}\n📍 {task[6] or '-'}\nپلان: {task[5]}%\n\n{resources_text}\nدرصد فعلی را انتخاب کنید:",
        reply_markup=report_keyboard(task_id)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("prog:"))
async def process_percent(callback: CallbackQuery, state: FSMContext):
    _, task_id, percent = callback.data.split(":")
    task_id, percent = int(task_id), int(percent)
    task = await get_task(task_id)
    if not task: return

    await state.update_data(pending_task_id=task_id, pending_percent=percent)
    await state.set_state(ReportAttach.waiting_attach)

    await callback.message.answer(
        f"✅ درصد {percent}% انتخاب شد.\n\nآیا می‌خواهید متن، عکس، فیلم یا فایل هم پیوست کنید؟",
        reply_markup=yes_no_keyboard("ra_")
    )
    await callback.answer()

@dp.callback_query(ReportAttach.waiting_attach, F.data.in_(["ra_yes", "ra_no"]))
async def report_attach_decision(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    task_id = data["pending_task_id"]
    percent = data["pending_percent"]
    task = await get_task(task_id)

    if callback.data == "ra_no":
        # ثبت درصد بدون پیوست
        await update_task_progress(task_id, percent)
        await add_report(task_id, percent)
        await send_report_to_admin(callback.from_user.id, task, percent)
        await state.clear()
        await callback.message.answer(
            f"✅ گزارش {percent}% ثبت شد.",
            reply_markup=report_keyboard(task_id)
        )
    else:
        await callback.message.answer("حالا متن، عکس، فیلم یا فایل را بفرستید:")

@dp.message(ReportAttach.waiting_attach, F.text | F.photo | F.video | F.document)
async def process_report_attach(message: Message, state: FSMContext):
    data = await state.get_data()
    task_id = data["pending_task_id"]
    percent = data["pending_percent"]
    task = await get_task(task_id)

    text_report = message.caption or message.text
    media_id = None
    if message.photo: media_id = message.photo[-1].file_id
    elif message.video: media_id = message.video.file_id
    elif message.document: media_id = message.document.file_id

    await update_task_progress(task_id, percent)
    await add_report(task_id, percent, text_report, media_id)
    await send_report_to_admin(message.from_user.id, task, percent, text_report, media_id, message)
    await state.clear()
    await message.answer(f"✅ گزارش {percent}% + پیوست ثبت شد.", reply_markup=report_keyboard(task_id))

async def send_report_to_admin(user_id, task, percent, text_report=None, media_id=None, original_message=None):
    user_info = await get_user_info_by_telegram_id(user_id)
    name = user_info[0] if user_info else "نامشخص"
    username = user_info[1] if user_info else "بدون یوزرنیم"
    photo_id = user_info[2] if user_info else None

    planned = task[5]
    calculated = round(planned * percent / 100, 1)
    remaining = planned - percent

    text = (
        f"📊 گزارش پیشرفت\n\n"
        f"👤 مسئول: {name} (@{username})\n"
        f"🆔 تسک #{task[0]}: {task[3]}\n"
        f"📍 موقعیت: {task[6] or '-'}\n"
        f"📈 درصد اعلام‌شده: {percent}%\n"
        f"🎯 پلان: {planned}%\n"
        f"🧮 پیشرفت محاسبه‌شده: {calculated}%\n"
        f"📉 باقی‌مانده: {remaining}%\n"
        f"🕐 ساعت: {now_iran().strftime('%H:%M')}"
    )
    if text_report:
        text += f"\n\n📝 توضیح مسئول:\n{text_report}"
    if calculated < planned:
        text += "\n⚠️ عقب از برنامه"

    # ارسال عکس مسئول + گزارش
    if photo_id:
        try:
            await bot.send_photo(ADMIN_ID, photo_id, caption=text)
        except:
            await bot.send_message(ADMIN_ID, text)
    else:
        await bot.send_message(ADMIN_ID, text)

    # ارسال پیوست مسئول
    if media_id and original_message:
        if original_message.photo:
            await bot.send_photo(ADMIN_ID, media_id, caption=f"پیوست گزارش تسک #{task[0]}")
        elif original_message.video:
            await bot.send_video(ADMIN_ID, media_id, caption=f"پیوست گزارش تسک #{task[0]}")
        elif original_message.document:
            await bot.send_document(ADMIN_ID, media_id, caption=f"پیوست گزارش تسک #{task[0]}")

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
    if current: return
    if message.from_user.id == ADMIN_ID: return
    # گزارش آزاد بدون درصد
    user_info = await get_user_info_by_telegram_id(message.from_user.id)
    name = user_info[0] if user_info else message.from_user.full_name
    username = user_info[1] if user_info else (message.from_user.username or "-")
    photo_id = user_info[2] if user_info else None
    caption = message.caption or message.text or "بدون توضیح"
    header = f"📎 گزارش آزاد از {name} (@{username})\n🕐 {now_iran().strftime('%H:%M')}\n\n{caption}"
    if photo_id:
        try: await bot.send_photo(ADMIN_ID, photo_id, caption=header)
        except: await bot.send_message(ADMIN_ID, header)
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
        if await is_confirmed(task_id): return
        try: await bot.send_message(tg_id, f"⏰ یادآوری ({i+1}/5)\nتسک «{task_name}» را تأیید کنید.")
        except: pass
    await asyncio.sleep(600)
    if not await is_confirmed(task_id):
        await bot.send_message(ADMIN_ID, f"🔴 آلارم\n@{username} تسک «{task_name}» را تأیید نکرد.\nساعت: {send_time}")

# ==================== زمان‌بندی ====================
async def daily_hours_ask():
    while True:
        now = now_iran()
        target = now.replace(hour=5, minute=0, second=0, microsecond=0)
        if now >= target: target += timedelta(days=1)
        await asyncio.sleep((target - now).total_seconds())
        try:
            await bot.send_message(ADMIN_ID, "⏰ ساعت ۵ صبح است.\nساعت کاری امروز را وارد کنید:\n/sethours 08:00 17:00")
        except: pass

async def end_of_day_report():
    while True:
        await asyncio.sleep(60)
        end_hour = await get_setting("end_hour")
        hours_date = await get_setting("hours_date")
        if not end_hour or not hours_date: continue
        now = now_iran()
        if hours_date != now.strftime("%Y-%m-%d"): continue
        try:
            h, m = map(int, end_hour.split(":"))
            end_time = now.replace(hour=h, minute=m, second=0, microsecond=0)
            report_time = end_time + timedelta(minutes=30)
            if now >= report_time and now < report_time + timedelta(minutes=1):
                await send_daily_summary(hours_date)
        except: pass

async def send_daily_summary(working_date: str):
    tasks = await get_today_tasks(working_date)
    if not tasks:
        await bot.send_message(ADMIN_ID, "گزارش پایان روز: تسکی ثبت نشده.")
        return
    summary = f"📊 گزارش نهایی روز {working_date}\n\n"
    stats = {}
    for task in tasks:
        task_id, name, username = task[0], task[3], task[4]
        planned, actual = task[5], task[9] or 0
        if username not in stats: stats[username] = 0
        stats[username] += 1
        summary += f"🔹 #{task_id}: {name}\n   @{username} | پلان {planned}% | واقعی {actual}% | باقی {planned-actual}%\n"
    summary += "\n📈 آمار:\n"
    for u, c in stats.items():
        summary += f"• @{u}: {c} تسک\n"
    await bot.send_message(ADMIN_ID, summary)

async def main():
    await init_db()
    asyncio.create_task(daily_hours_ask())
    asyncio.create_task(end_of_day_report())
    print("ربات روشن شد (مرحله ۱ کامل)...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())