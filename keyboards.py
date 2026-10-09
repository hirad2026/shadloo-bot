from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def status_keyboard(task_id: int):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ انجام شد", callback_data=f"status:{task_id}:done")],
        [InlineKeyboardButton(text="🟢 در حال انجام مطلوب", callback_data=f"status:{task_id}:good")],
        [InlineKeyboardButton(text="🟡 در حال انجام با تأخیر", callback_data=f"status:{task_id}:delay")],
        [InlineKeyboardButton(text="🔴 معوق", callback_data=f"status:{task_id}:overdue")]
    ])
    return keyboard