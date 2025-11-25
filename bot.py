import os
import json
import re
from datetime import datetime
from flask import Flask
from threading import Thread
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from utils import parse_expense_with_gemini, add_expense, delete_expense, get_chat_response, collection

# --- CONFIGURATION ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
DASHBOARD_URL = "http://localhost:8501" 

# --- KEEP ALIVE ---
flask_app = Flask('')
@flask_app.route('/')
def home(): return "Alive"
def run_http(): flask_app.run(host='0.0.0.0', port=8080)
def keep_alive():
    t = Thread(target=run_http)
    t.start()

# --- HELPER: EMOJI MAP ---
def get_category_emoji(category):
    map = {
        "Food": "🍔", "Groceries": "🥦", "Travel": "🚖", "Medical": "💊",
        "Subscriptions": "📅", "Electronics": "🔌", "Shopping": "🛍️",
        "Education": "📚", "Gifts": "🎁", "Outings": "🎉", 
        "Rent & Utilities": "🏠", "Investments": "📈", "Entertainment": "🎬",
        "Personal Care": "🧴", "Loans/EMI": "🏦", "Debt": "📝", 
        "Loan Given": "🤝", "Miscellaneous": "📦"
    }
    return map.get(category, "💵")

# --- HELPER: FORMAT DATA ---
def format_transactions(cursor_list):
    clean_data = []
    for entry in cursor_list:
        date_str = entry['date'].strftime('%Y-%m-%d')
        clean_entry = {"Date": date_str, "Item": entry['i'], "Amount": entry['a'], "Category": entry['c']}
        if entry.get('n'): clean_entry["Note"] = entry['n']
        clean_data.append(clean_entry)
    return json.dumps(clean_data)

# --- EMERGENCY FALLBACK PARSER ---
def manual_fallback_parse(text):
    """
    If AI fails, try to capture 'Item Amount' using simple regex.
    """
    match = re.search(r'^(.+?)\s+(\d+(\.\d+)?)$', text)
    if match:
        item = match.group(1).strip().title()
        amount = float(match.group(2))
        return [{
            "action": "add",
            "i": item,
            "a": amount,
            "c": "Miscellaneous", 
            "n": "Manual Fallback"
        }]
    return None

# --- BOT LOGIC ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    
    user_text = update.message.text
    user_id = update.effective_user.id
    text_lower = user_text.lower()
    
    # 1. TRY AI PARSING
    parsed_list = parse_expense_with_gemini(user_text)

    # 2. IF AI FAILS, TRY MANUAL FALLBACK
    if parsed_list is None:
        parsed_list = manual_fallback_parse(user_text)

    # 3. IF BOTH FAIL -> ASSUME CHAT / ANALYSIS
    if parsed_list is None or "?" in user_text or "how" in text_lower or "total" in text_lower:
        
        if "dashboard" in text_lower:
             await update.message.reply_text(f"📊 **Dashboard:**\n{DASHBOARD_URL}", parse_mode='Markdown')
             return
        
        cursor = collection.find({}, {"_id": 0}).sort("date", -1).limit(300)
        data_list = list(cursor)

        if not data_list:
            await update.message.reply_text("📂 No data found yet.")
            return

        clean_context_str = format_transactions(data_list)
        processing_msg = await update.message.reply_text(f"🤔 Analyzing...")
        
        answer = get_chat_response(user_text, clean_context_str)
        
        try:
            await context.bot.edit_message_text(chat_id=user_id, message_id=processing_msg.message_id, text=answer, parse_mode='Markdown')
        except:
            await context.bot.edit_message_text(chat_id=user_id, message_id=processing_msg.message_id, text=answer, parse_mode=None)
        
    # 4. SAVE TRANSACTION
    else:
        reply_lines = []
        for data in parsed_list:
            if data.get('action') == 'delete':
                success, item, date = delete_expense(data)
                if success: 
                    d_str = date.strftime('%d %b')
                    reply_lines.append(f"🗑️ **Deleted:** {item} ({data['a']})")
                else: 
                    reply_lines.append(f"⚠️ **Not Found:** {data['i']}")
            else:
                add_expense(data)
                
                # Get Emoji
                emoji = get_category_emoji(data['c'])
                if data['a'] < 0: emoji = "🤑"
                
                line = f"{emoji} **{data['i']}**\n     └ {data['a']}  |  _{data['c']}_"
                
                if data.get('n') and "Manual" not in data['n']: 
                    line += f"\n     └ 📌 {data['n']}"
                
                reply_lines.append(line)

        summary = "\n\n".join(reply_lines)
        receipt = f"🧾 **Transaction Saved**\n────────────────\n{summary}\n────────────────\n📊 [Dashboard]({DASHBOARD_URL})"
        try:
            await update.message.reply_text(receipt, parse_mode='Markdown')
        except:
            await update.message.reply_text(receipt, parse_mode=None)

if __name__ == '__main__':
    keep_alive()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    echo_handler = MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message)
    app.add_handler(echo_handler)
    print("Bot is running...")
    app.run_polling()

# import os
# from flask import Flask
# from threading import Thread

# flask_app = Flask('')

# @flask_app.route('/')
# def home():
#     return "I am alive!"

# def run_http():
#     flask_app.run(host='0.0.0.0', port=8080)

# def keep_alive():
#     t = Thread(target=run_http)
#     t.start()

# from telegram import Update
# from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
# from utils import parse_expense_with_gemini, add_expense, delete_expense, get_chat_response, collection

# # --- CONFIGURATION ---
# # ⚠️ PASTE YOUR TELEGRAM TOKEN HERE
# TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
# DASHBOARD_URL = "http://financeproject-daozlrb2223siae3uzttph.streamlit.app"

# async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     # Safety check: Ignore edits or non-text updates
#     if not update.message or not update.message.text: return
    
#     user_text = update.message.text
#     user_id = update.effective_user.id
    
#     # 1. DASHBOARD / QUESTIONS
#     text_lower = user_text.lower()
#     if "?" in user_text or "how" in text_lower or "show" in text_lower or "dashboard" in text_lower or "owe" in text_lower:
        
#         if "dashboard" in text_lower:
#              await update.message.reply_text(f"📊 Dashboard: {DASHBOARD_URL}")
#              return
        
#         # Fetch context for AI
#         cursor = collection.find({}, {"_id": 0}).sort("date", -1).limit(30)
#         data_context = list(cursor)
        
#         processing_msg = await update.message.reply_text(f"🤔 Analyzing...")
#         answer = get_chat_response(user_text, str(data_context))
#         await context.bot.edit_message_text(chat_id=user_id, message_id=processing_msg.message_id, text=answer)
        
#     # 2. TRANSACTION PROCESSING (BATCH SUPPORT)
#     else:
#         parsed_list = parse_expense_with_gemini(user_text)
        
#         if parsed_list:
#             reply_lines = []
            
#             # Loop through every item found
#             for data in parsed_list:
#                 if data.get('action') == 'delete':
#                     success = delete_expense(data)
#                     if success: reply_lines.append(f"🗑️ Deleted: {data['i']}")
#                     else: reply_lines.append(f"⚠️ Not found: {data['i']}")
#                 else:
#                     add_expense(data)
                    
#                     # Icon Logic
#                     if data['c'] == 'Debt': icon = "📝"
#                     elif data['a'] < 0: icon = "🤑"
#                     else: icon = "✅"
                    
#                     # Build line
#                     line = f"{icon} {data['i']}: {data['a']} ({data['c']})"
                    
#                     # Append Note if it exists
#                     if data.get('n'):
#                         line += f"\n   └ 📌 _{data['n']}_"
                    
#                     reply_lines.append(line)

#             # Send Summary
#             summary = "\n".join(reply_lines)
#             await update.message.reply_text(f"**Saved:**\n\n{summary}\n────────────────\n📊 {DASHBOARD_URL}", parse_mode='Markdown')
            
#         else:
#             await update.message.reply_text("😅 I didn't understand.")

# if __name__ == '__main__':
#     keep_alive()
#     app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
#     echo_handler = MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message)
#     app.add_handler(echo_handler)
#     print("Bot is running...")
#     app.run_polling()










