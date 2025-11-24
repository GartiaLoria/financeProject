import os
import google.generativeai as genai
from pymongo import MongoClient
from datetime import datetime
import json
import re
import certifi

# --- CONFIGURATION ---
MONGO_URI = os.getenv("MONGO_URI")
GEMINI_KEY = os.getenv("GEMINI_KEY")

# --- SETUP ---
cluster = MongoClient(MONGO_URI, tlsCAFile=certifi.where())
db = cluster["expense_tracker"]
collection = db["expenses"]

genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-2.5-flash')

# --- FUNCTIONS ---

def clean_json_string(text):
    text = text.replace('```json', '').replace('```', '').strip()
    if text.startswith('['):
        start = text.find('[')
        end = text.rfind(']')
        if start != -1 and end != -1: return text[start:end+1]
    else:
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1: return text[start:end+1]
    return text

def parse_expense_with_gemini(user_text):
    """
    Extracts transactions using YOUR EXACT DEFINITIONS.
    """
    prompt = f"""
    You are a specialized Expense Tracker Parser. 
    User Input: "{user_text}"
    
    Task: Extract transactions into a JSON LIST.
    
    --- MATH RULE ---
    Always interpret entries of the form A/B as A divided by B = my share.
    (Example: "Uber 100/2" -> Amount is 50).

    --- CATEGORY CLASSIFICATION RULES ---
    1. Food: Meals, drinks, snacks, tea, restaurant, meal plans. NOT Outings.
    2. Groceries: Raw kitchen items, fruits, vegetables, grains, spices.
    3. Travel: Bus, auto, cab, bike, fuel, train, flight.
    4. Medical: Doctor, medicine, tests, pharmacy, supplements.
    5. Subscriptions: Netflix, Spotify, Gym, Cloud, Apps, Prime, Memberships.
    6. Electronics: Gadgets, phones, chargers, repairs, appliances, headphones.
    7. Shopping: Clothes, shoes, bags, accessories, watches, wallets.
    8. Education: Books, courses, exams, stationery, work materials, skill dev.
    9. Gifts: Birthday treats, gifts for others. NOT Outings.
    10. Outings: Hangouts, events, festivals, clubs, trips.
    11. Rent & Utilities: Rent, electricity, water, maintenance.
    12. Investments: Savings, deposits, mutual funds.
    13. Entertainment: Movie tickets, games, events (non-outing).
    14. Personal Care: Soap, shampoo, cosmetics, hygiene.
    15. Loans/EMI: Repaying loans, EMIs.
    16. Miscellaneous: Anything else.

    --- FIELDS ---
    'action': 'delete' if removing/undoing, else 'add'.
    'i': Item Name.
    'a': Amount (+ for expense/lending, - for income/repayment).
    'c': Category (Use the exact names from above).
    'n': Context Note (Only if "save c" or "context" is present).
    
    Output JSON LIST:
    [
      {{"action": "add", "i": "Item", "a": 50, "c": "Category", "n": ""}}
    ]
    """
    try:
        response = model.generate_content(prompt)
        cleaned_text = clean_json_string(response.text)
        data = json.loads(cleaned_text)
        
        if isinstance(data, dict): data = [data]
            
        for entry in data:
            if 'i' in entry: entry['i'] = str(entry['i']).title()
            if 'c' in entry: entry['c'] = str(entry['c']).title()
            if 'a' in entry: entry['a'] = float(entry['a'])
            if 'n' not in entry: entry['n'] = ""
            
        return data
    except Exception as e:
        print(f"Parsing Error: {e}")
        return None

def add_expense(data):
    entry = {
        "i": data['i'], "a": data['a'], "c": data['c'], 
        "n": data.get('n', ""), "date": datetime.now()
    }
    collection.insert_one(entry)

def delete_expense(data):
    query = {"a": data['a'], "i": {"$regex": data['i'], "$options": "i"}}
    matches = list(collection.find(query).sort("date", -1))
    
    if len(matches) > 0:
        target = matches[0]
        collection.delete_one({"_id": target["_id"]})
        return True, target['i'], target['date']
    return False, None, None

def get_chat_response(query, user_data_context):
    prompt = f"""
    You are a Financial Analyst Assistant.
    User Data (JSON): {user_data_context}
    User Question: {query}
    
    RESPONSE FORMATTING RULES:
    1. **Group by Item:** Group similar entries (e.g., all "Bus" entries together).
    2. **Show Details:** Under the group name, list the individual transactions.
    3. **Format:** Use a bullet point '•' followed by: `Amount (Date)`.
    4. **Context:** If a note ('n') exists, add it next to the date in *italics*.
    5. **Totals:** Show the total for that item group in Bold.
    6. **Grand Total:** Show at the bottom.
    
    EXAMPLE OUTPUT:
    
    🚌 **Bus** (Total: 384.5)
    • 31.5 (01 Nov)
    • 4.5 (02 Nov) - *to office*
    
    **Grand Total: ...**
    """
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return "⚠️ My brain is fuzzy right now. Ask me again in a minute!"

# import os
# import google.generativeai as genai
# from pymongo import MongoClient
# from datetime import datetime
# import json
# import re
# import certifi

# # --- CONFIGURATION ---
# MONGO_URI = os.getenv("MONGO_URI")
# GEMINI_KEY = os.getenv("GEMINI_KEY")

# # --- SETUP ---
# cluster = MongoClient(MONGO_URI, tlsCAFile=certifi.where())
# db = cluster["expense_tracker"]
# collection = db["expenses"]

# genai.configure(api_key=GEMINI_KEY)
# model = genai.GenerativeModel('gemini-2.5-flash')

# # --- FUNCTIONS ---

# def clean_json_string(text):
#     text = text.replace('```json', '').replace('```', '').strip()
#     if text.startswith('['):
#         start = text.find('[')
#         end = text.rfind(']')
#         if start != -1 and end != -1: return text[start:end+1]
#     else:
#         start = text.find('{')
#         end = text.rfind('}')
#         if start != -1 and end != -1: return text[start:end+1]
#     return text

# def parse_expense_with_gemini(user_text):
#     prompt = f"""
#     You are a specialized Expense Tracker Parser. 
#     User Input: "{user_text}"
    
#     Task: Extract transactions into a JSON LIST.
    
#     --- MATH RULE ---
#     If amount is "A/B" (e.g. "100/2"), CALCULATE it (e.g. 50).

#     --- CATEGORY RULES (STRICT) ---
#     1. Food: Meals, drinks, snacks, tea, restaurant, meal plans. NOT Outings.
#     2. Groceries: Raw kitchen items, fruits, vegetables, grains, spices.
#     3. Travel: Bus, auto, cab, bike, fuel, train, flight.
#     4. Medical: Doctor, medicine, tests, pharmacy, supplements.
#     5. Subscriptions: Netflix, Spotify, Gym, Cloud, Apps, Prime, Memberships.
#     6. Electronics: Gadgets, phones, chargers, repairs, appliances, headphones.
#     7. Shopping: Clothes, shoes, bags, accessories, watches, wallets.
#     8. Education: Books, courses, exams, stationery, work materials, skill dev.
#     9. Gifts: Birthday treats, gifts for others. NOT Outings.
#     10. Outings: Hangouts, events, festivals, clubs, trips.
#     11. Rent & Utilities: Rent, electricity, water, maintenance.
#     12. Investments: Savings, deposits, mutual funds.
#     13. Entertainment: Movie tickets, games, events (non-outing).
#     14. Personal Care: Soap, shampoo, cosmetics, hygiene.
#     15. Loans/EMI: Repaying loans, EMIs.
#     16. Miscellaneous: Anything else.

#     --- OUTPUT FORMAT ---
#     Return JSON LIST:
#     [
#       {{"action": "add", "i": "Netflix", "a": 199, "c": "Subscriptions", "n": "Monthly"}}
#     ]
#     """
#     try:
#         response = model.generate_content(prompt)
#         cleaned_text = clean_json_string(response.text)
#         data = json.loads(cleaned_text)
        
#         if isinstance(data, dict): data = [data]
            
#         for entry in data:
#             if 'i' in entry: entry['i'] = str(entry['i']).title()
#             if 'c' in entry: entry['c'] = str(entry['c']).title()
#             if 'a' in entry: entry['a'] = float(entry['a'])
#             if 'n' not in entry: entry['n'] = ""
            
#         return data
#     except Exception as e:
#         print(f"Parsing Error: {e}")
#         return None

# def add_expense(data):
#     entry = {
#         "i": data['i'], "a": data['a'], "c": data['c'], 
#         "n": data.get('n', ""), "date": datetime.now()
#     }
#     collection.insert_one(entry)

# def delete_expense(data):
#     query = {"a": data['a'], "i": {"$regex": data['i'], "$options": "i"}}
#     matches = list(collection.find(query).sort("date", -1))
#     if len(matches) > 0:
#         target = matches[0]
#         collection.delete_one({"_id": target["_id"]})
#         return True, target['i'], target['date']
#     return False, None, None

# def get_chat_response(query, user_data_context):
#     prompt = f"""
#     You are a Financial Analyst.
#     User Data (JSON): {user_data_context}
#     User Question: {query}
#     Instructions:
#     - Filter data by date relative to today ({datetime.now().strftime('%Y-%m-%d')}).
#     - Sum amounts accurately.
#     - Keep answers short.
#     """
#     response = model.generate_content(prompt)
#     return response.text

# import os
# import google.generativeai as genai
# from pymongo import MongoClient
# from datetime import datetime
# import json
# import re
# import certifi

# # --- CONFIGURATION ---
# # ⚠️ PASTE YOUR ACTUAL KEYS HERE
# MONGO_URI = os.getenv("MONGO_URI")
# GEMINI_KEY = os.getenv("GEMINI_KEY")

# # --- SETUP ---
# # We use certifi to prevent SSL errors on Windows
# cluster = MongoClient(MONGO_URI, tlsCAFile=certifi.where())
# db = cluster["expense_tracker"]
# collection = db["expenses"]

# genai.configure(api_key=GEMINI_KEY)
# model = genai.GenerativeModel('gemini-2.5-flash')

# # --- FUNCTIONS ---

# def clean_json_string(text):
#     """
#     Robust cleaner: Handles both Single Objects {} and Lists []
#     """
#     text = text.replace('```json', '').replace('```', '').strip()
    
#     # If it looks like a list
#     if text.startswith('['):
#         start = text.find('[')
#         end = text.rfind(']')
#         if start != -1 and end != -1: return text[start:end+1]
#     # If it looks like a single object
#     else:
#         start = text.find('{')
#         end = text.rfind('}')
#         if start != -1 and end != -1: return text[start:end+1]
        
#     return text

# def parse_expense_with_gemini(user_text):
#     """
#     Extracts transactions into a JSON LIST. 
#     Looks for 'save c' to extract context notes.
#     """
#     prompt = f"""
#     You are a Data Extraction API. 
#     User Input: "{user_text}"
    
#     Task: Extract ALL transactions into a JSON LIST.
    
#     RULES for 'n' (Note/Context):
#     - CHECK: Does input contain code "save c" or "context"?
#     - IF YES: Extract description (e.g. "for dinner", "with team") into field 'n'.
#     - IF NO: Field 'n' must be empty string "".
    
#     RULES for 'c' (Category):
#     - If user says "Owe", "Payable", "Give [Person]" (Future tense) -> Category is "Debt".
#     - If user says "Lent", "Given" (Past tense) -> Category is "Loan Given".
#     - Otherwise -> Normal Category (Food, Travel, etc).

#     RULES for 'a' (Amount):
#     - POSITIVE (+): Expense, Lending, Debt (Money leaves you).
#     - NEGATIVE (-): Income, Repayment (Money comes to you).
    
#     Output ONLY a JSON LIST:
#     [
#       {{"action": "add", "i": "Item", "a": 100, "c": "Category", "n": "note here"}}
#     ]
#     """
#     try:
#         response = model.generate_content(prompt)
#         cleaned_text = clean_json_string(response.text)
#         data = json.loads(cleaned_text)
        
#         # Ensure it's always a list
#         if isinstance(data, dict): data = [data]
            
#         # Sanitize Data
#         for entry in data:
#             if 'i' in entry: entry['i'] = str(entry['i']).title()
#             if 'c' in entry: entry['c'] = str(entry['c']).title()
#             if 'a' in entry: entry['a'] = float(entry['a'])
#             if 'n' not in entry: entry['n'] = "" # Default to empty note
            
#         return data
#     except Exception as e:
#         print(f"Parsing Error: {e}")
#         print(f"Raw Output: {response.text}")
#         return None

# def add_expense(data):
#     entry = {
#         "i": data['i'], 
#         "a": data['a'], 
#         "c": data['c'], 
#         "n": data.get('n', ""), 
#         "date": datetime.now()
#     }
#     collection.insert_one(entry)

# def delete_expense(data):
#     # Find entry matching amount and similar item name
#     query = {"a": data['a'], "i": {"$regex": data['i'], "$options": "i"}}
#     target = collection.find_one(query, sort=[("date", -1)])
#     if target:
#         collection.delete_one({"_id": target["_id"]})
#         return True
#     return False

# def get_chat_response(query, user_data_context):
#     prompt = f"""
#     Context: {user_data_context}
#     User Question: {query}
#     Answer concisely. Use emojis. Do not use bold markdown (**).
#     """
#     response = model.generate_content(prompt)

#     return response.text


