import asyncio
import logging
import re
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message
from dotenv import load_dotenv
import os

from database import init_db, add_user, add_task, get_all_users, get_tasks_by_date

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

logging.basicConfig(level=logging.INFO)

@dp.message(Command("start"))
async def cmd_start(message: Message):
    if message.from_user.id == ADMIN_ID:
        await message.answer("سلام آقای شادلو\nربات آماده است.\n\nدستورات:\n/adduser نام یوزرنیم\n/addtask\n/list\n/users")
    else:
        await message.answer("شما به عنوان مسئول ثبت شدید.")

@dp.message(Command("adduser"))
async def cmd_adduser(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        parts = message.text.split(maxsplit=2)
        await add_user(parts[1], parts[2])
        await message.answer(f"✅ مسئول {parts[1]} اضافه شد.")
    except:
        await message.answer("فرمت: /adduser نام یوزرنیم")

@dp.message(Command("users"))
async def cmd_users(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    users = await get_all_users()
    if not users:
        await message.answer("مسئولی ثبت نشده.")
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
            await message.answer("نام تسک و منابع را داخل \" \" بگذارید.")
            return
        task_name = parts[0]
        resources = parts[1]
        remaining = text
        for p in parts:
            remaining = remaining.replace(f'"{p}"', "")
        remaining_parts = remaining.split()
        if len(remaining_parts) < 4:
            await message.answer("فرمت کامل نیست.")
            return
        date = remaining_parts[0]
        time = remaining_parts[1]
        username = remaining_parts[2]
        percent = int(remaining_parts[3])
        await add_task(date, time, task_name, username, percent, resources)
        await message.answer(f"✅ تسک ثبت شد:\n{task_name}\nمسئول: @{username}\nپلان: {percent}%")
    except Exception as e:
        await message.answer(f"خطا: {e}")

@dp.message(Command("list"))
async def cmd_list(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("برای دیدن تسک‌ها فعلاً از دستور /list استفاده کنید (به‌زودی کامل می‌شود).")

async def main():
    await init_db()
    print("ربات روشن شد...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())