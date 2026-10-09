import asyncio
import logging
import re
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from dotenv import load_dotenv
import os

from database import init_db, add_user, add_task, get_all_users, get_tasks_by_date, update_task_status
from keyboards import status_keyboard
from scheduler import start_scheduler

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

logging.basicConfig(level=logging.INFO)

@dp.message(Command("start"))
async def cmd_start(message: Message):
    if message.from_user.id == ADMIN_ID:
        await message.answer("سلام آقای شادلو\nربات کنترل پروژه آماده است.\n\nدستورات:\n/adduser\n/addtask\n/list\n/users")
    else:
        await message.answer("شما به عنوان مسئول ثبت‌نام شدید. منتظر پیام‌های ربات باشید.")

@dp.message(Command("adduser"))
async def cmd_adduser(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        parts = message.text.split(maxsplit=2)
        full_name = parts[1]
        username = parts[2]
        await add_user(full_name, username)
        await message.answer(f"✅ مسئول {full_name} با یوزرنیم {username} اضافه شد.")
    except:
        await message.answer("فرمت اشتباه است.\nمثال:\n/adduser علی رضایی ali_rezaei")

@dp.message(Command("users"))
async def cmd_users(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    users = await get_all_users()
    if not users:
        await message.answer("هنوز مسئولی ثبت نشده.")
        return
    text = "لیست مسئولین:\n\n"
    for name, username in users:
        text += f"• {name} → @{username}\n"
    await message.answer(text)

@dp.message(Command("addtask"))
async def cmd_addtask(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    try:
        text = message.text.replace("/addtask", "").strip()
        
        parts = re.findall(r'"([^"]*)"', text)
        
        if len(parts) < 2:
            await message.answer("فرمت اشتباه است.\nحتماً نام تسک و منابع را داخل گیومه بگذارید.")
            return

        task_name = parts[0]
        resources = parts[1]

        remaining = text
        for p in parts:
            remaining = remaining.replace(f'"{p}"', "")
        
        remaining_parts = remaining.split()
        
        if len(remaining_parts) < 4:
            await message.answer("فرمت ناقص است.\nمثال صحیح:\n/addtask 2026-10-10 08:00 \"بتن‌ریزی سقف\" shadloo2023 40 \"میلگرد ۵ تن\"")
            return

        date = remaining_parts[0]
        time = remaining_parts[1]
        username = remaining_parts[2]
        planned_percent = int(remaining_parts[3])

        await add_task(date, time, task_name, username, planned_percent, resources)
        
        await message.answer(
            f"✅ تسک با موفقیت ثبت شد:\n\n"
            f"📅 تاریخ: {date}\n"
            f"⏰ ساعت: {time}\n"
            f"📝 تسک: {task_name}\n"
            f"👤 مسئول: @{username}\n"
            f"📊 پلان: {planned_percent}%\n"
            f"📦 منابع: {resources}"
        )

    except Exception as e:
        await message.answer(f"خطا در ثبت تسک:\n{str(e)}")

@dp.message(Command("list"))
async def cmd_list(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    tasks = await get_tasks_by_date(today)
    if not tasks:
        await message.answer("تسکی برای امروز ثبت نشده.")
        return
    text = "تسک‌های امروز:\n\n"
    for t in tasks:
        text += f"ID: {t[0]} | {t[3]} | مسئول: {t[4]} | پلان: {t[5]}%\n"
    await message.answer(text)

async def main():
    await init_db()
    start_scheduler(bot, ADMIN_ID)
    print("ربات روشن شد...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())