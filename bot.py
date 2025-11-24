import os
from flask import Flask
from threading import Thread
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from utils import parse_expense_with_gemini, add_expense, delete_expense, get_chat_response, collection

# --- CONFIGURATION ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
DASHBOARD_URL = "https://your-app-url.onrender.com" # ⚠️ Put your real Render/Streamlit link here

# --- EXPANDED EMOJI MAP ---
CATEGORY_EMOJIS = {
    "Food": "🍔", 
    "Groceries": "🥦", 
    "Travel": "🚕", 
    "Medical": "💊",
    "Subscriptions": "📅",
    "Electronics": "🔌",
    "Shopping": "🛍️",
    "Education": "📚",
    "Gifts": "🎁", 
    "Outings": "🎉", 
    "Rent & Utilities": "🏠", 
    "Investments": "📈", 
    "Entertainment": "🍿", 
    "Personal Care": "🧴", 
    "Loans/EMI": "🏦", 
    "Debt": "📝", 
    "Loan Given": "🤝", 
    "Miscellaneous": "📦"
}

# --- KEEP ALIVE ---
flask_app = Flask('')
@flask_app.route('/')
def home(): return "Alive"
def run_http(): flask_app.run(host='0.0.0.0', port=8080)
def keep_alive():
    t = Thread(target=run_http)
    t.start()

# --- BOT LOGIC ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    
    user_text = update.message.text
    user_id = update.effective_user.id
    text_lower = user_text.lower()
    
    # --- STEP 1: PARSE INTENT ---
    parsed_list = parse_expense_with_gemini(user_text)

    # --- PATH A: CHAT / ANALYSIS ---
    if parsed_list is None or "?" in user_text or any(k in text_lower for k in ["how", "total", "calculate", "summary", "breakdown"]):
        
        if "dashboard" in text_lower:
             await update.message.reply_text(f"📊 [Click to Open Dashboard]({DASHBOARD_URL})", parse_mode='Markdown')
             return
        
        # Memory: 300 Items
        cursor = collection.find({}, {"_id": 0}).sort("date", -1).limit(300)
        data_context = list(cursor)

        if not data_context:
            await update.message.reply_text("📂 No data found yet.")
            return

        processing_msg = await update.message.reply_text(f"🤔 Analyzing...")
        answer = get_chat_response(user_text, str(data_context))
        await context.bot.edit_message_text(chat_id=user_id, message_id=processing_msg.message_id, text=answer, parse_mode='Markdown')
        
    # --- PATH B: TRANSACTION ---
    else:
        reply_lines = []
        for data in parsed_list:
            if data.get('action') == 'delete':
                success, item, date = delete_expense(data)
                if success: 
                    d_str = date.strftime('%d %b')
                    reply_lines.append(f"🗑️ **Deleted:** {item} ({data['a']}) from {d_str}")
                else: 
                    reply_lines.append(f"⚠️ **Not Found:** {data['i']} ({data['a']})")
            else:
                add_expense(data)
                
                # Dynamic Emoji Logic
                cat = data['c']
                icon = CATEGORY_EMOJIS.get(cat, "✅") # Default to ✅ if category not in list
                if data['a'] < 0: icon = "💰" 
                
                line = f"{icon} **{data['i']}**: {data['a']} _({cat})_"
                if data.get('n'): line += f"\n   └ 📌 {data['n']}"
                reply_lines.append(line)

        summary = "\n".join(reply_lines)
        
        msg = (
            f"✨ **Transaction Saved**\n\n"
            f"{summary}\n"
            f"────────────────\n"
            f"📈 [Open Dashboard]({DASHBOARD_URL})"
        )
        await update.message.reply_text(msg, parse_mode='Markdown')

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




