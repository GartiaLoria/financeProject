import os
import google.generativeai as genai
from pymongo import MongoClient
from datetime import datetime, timedelta
import json
import re
import pandas as pd # <--- The Math Engine
import certifi

# --- CONFIGURATION ---
MONGO_URI = os.getenv("MONGO_URI")
GEMINI_KEY = os.getenv("GEMINI_KEY")

# --- SETUP ---
# We use certifi to ensure SSL works on all devices
cluster = MongoClient(MONGO_URI, tlsCAFile=certifi.where())
db = cluster["expense_tracker"]
collection = db["expenses"]

genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-2.5-flash')

# --- HELPER FUNCTIONS ---

def clean_json_string(text):
    """
    Cleans Gemini output to ensure valid JSON.
    """
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
    Extracts transactions using STRICT USER RULES & 18 CATEGORIES.
    """
    prompt = f"""
    You are a specialized Data Extractor. User Input: "{user_text}"
    
    STEP 1: IDENTIFY INTENT
    - Is the user asking a question, asking for a breakdown, or correcting a previous calculation? -> Return {{"is_chat": true}}
    - Is the user entering transaction data? -> Extract the data.

    STEP 2: EXTRACT DATA (If transaction)
    - MATH: Calculate "A/B" immediately (e.g. "100/2" -> 50).
    - NOTE: Extract context note into 'n' only if user says "save c", "context", or "note".

    STEP 3: CATEGORIZE (STRICT 18 RULES)
    1. Food: Meals, drinks, snacks, tea, restaurant, meal plans. NOT Outings.
    2. Groceries: Raw kitchen items, fruits, vegetables, grains, spices.
    3. Travel: Bus, auto, cab, bike, fuel, train, flight.
    4. Medical: Doctor, medicine, tests, pharmacy, supplements.
    5. Subscriptions: Netflix, Spotify, Gym, Cloud, Apps, Prime, Memberships.
    6. Electronics: Gadgets, phones, chargers, repairs, appliances, headphones.
    7. Shopping: Clothes, shoes, bags, accessories, watches, wallets.
    8. Education: Books, courses, exams, stationery, work materials, skill dev.
    9. Gifts: Birthday treats, gifts for others. NOT Outings.
    10. Outings: Hangouts, events, festivals (Balijatra), clubs, trips.
    11. Rent & Utilities: Rent, electricity, water, maintenance.
    12. Investments: Savings, deposits, mutual funds.
    13. Entertainment: Movie tickets, games, events (non-outing).
    14. Personal Care: Soap, shampoo, cosmetics, hygiene.
    15. Loans/EMI: Repaying loans, EMIs.
    16. Miscellaneous: Anything else.
    17. Debt: Future payments ("Owe", "Will pay", "Bill due").
    18. Loan Given: Past payments to others ("Lent", "Gave").
    
    Output JSON (Transaction):
    [ {{"action": "add", "i": "Item", "a": 50, "c": "Category", "n": ""}} ]
    
    Output JSON (Chat):
    {{ "is_chat": true }}
    """
    try:
        response = model.generate_content(prompt)
        cleaned_text = clean_json_string(response.text)
        data = json.loads(cleaned_text)
        
        # Check Intent
        if isinstance(data, dict) and data.get("is_chat"): return None
        if isinstance(data, dict): data = [data]
        
        valid_data = []
        for entry in data:
            if 'a' not in entry: continue 
            if 'i' in entry: entry['i'] = str(entry['i']).title()
            if 'c' in entry: entry['c'] = str(entry['c']).title()
            if 'a' in entry: entry['a'] = float(entry['a'])
            if 'n' not in entry: entry['n'] = ""
            valid_data.append(entry)
            
        return valid_data if valid_data else None

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
    # Find matching amount and similar item name
    query = {"a": data['a'], "i": {"$regex": data['i'], "$options": "i"}}
    matches = list(collection.find(query).sort("date", -1))
    
    if len(matches) > 0:
        target = matches[0]
        collection.delete_one({"_id": target["_id"]})
        return True, target['i'], target['date']
    return False, None, None

def get_chat_response(query, data_list):
    """
    Uses PANDAS for 100% accurate math, then Gemini for formatting.
    """
    if not data_list: return "📂 No data found."

    # 1. PANDAS CALCULATION ENGINE
    # We load data into a DataFrame (like an Excel sheet in memory)
    df = pd.DataFrame(data_list)
    df['date'] = pd.to_datetime(df['date'])

    # 2. ASK GEMINI FOR FILTERS ONLY
    today = datetime.now().strftime("%Y-%m-%d")
    filter_prompt = f"""
    User Query: "{query}" | Current Date: {today}
    
    Task: Extract search filters for a Database.
    Return JSON ONLY:
    {{
      "categories": ["Food", "Travel"], (List of strings. Empty [] if all)
      "start_date": "YYYY-MM-DD", (Calculate based on 'November', 'Last week', etc.)
      "end_date": "YYYY-MM-DD",
      "intent": "summary" or "breakdown"
    }}
    """
    try:
        response = model.generate_content(filter_prompt)
        filters = json.loads(clean_json_string(response.text))
        
        # 3. APPLY FILTERS IN PYTHON (Precise Math)
        filtered_df = df.copy()
        
        # Filter Date
        if filters.get('start_date'): 
            filtered_df = filtered_df[filtered_df['date'] >= filters['start_date']]
        if filters.get('end_date'): 
            filtered_df = filtered_df[filtered_df['date'] <= filters['end_date']]
            
        # Filter Category
        if filters.get('categories'): 
            # Case-insensitive match
            filtered_df = filtered_df[filtered_df['c'].astype(str).str.lower().isin([x.lower() for x in filters['categories']])]

        # 4. CALCULATE TOTALS
        total_sum = filtered_df['a'].sum()
        
        # Prepare breakdown data
        breakdown_text = ""
        if filters.get('intent') == "breakdown":
            # List details: Date | Item | Amount
            details = filtered_df.sort_values(by='date', ascending=False)
            breakdown_text = details[['date', 'i', 'a']].to_string(index=False)
        else:
            # Group by Category: Category | Sum
            cat_group = filtered_df.groupby('c')['a'].sum().to_dict()
            breakdown_text = str(cat_group)

        # 5. FINAL FORMATTING (Gemini writes the receipt)
        final_prompt = f"""
        You are a Financial Analyst.
        User Query: "{query}"
        
        I have calculated the EXACT math using Python. Do NOT recalculate.
        DATA TO REPORT:
        - Total Sum: {total_sum}
        - Breakdown Data: {breakdown_text}
        
        INSTRUCTIONS:
        1. Start with the Grand Total (e.g., "💰 Total: 500").
        2. If 'Breakdown Data' is a dictionary, list totals by category with emojis.
        3. If 'Breakdown Data' is a list of items, show the date and item details.
        4. Use these emojis:
           Food:🍜, Groceries:🥦, Travel:🚖, Medical:💊, Subscriptions:💳, Electronics:💻, 
           Shopping:🛍️, Education:📚, Gifts:🎁, Outings:🎡, Rent:⚡, Investments:💸, 
           Entertainment:🎬, Personal Care:🛁, Loans:🏦, Misc:📦.
        5. Keep it clean and readable.
        """
        final_resp = model.generate_content(final_prompt)
        return final_resp.text

    except Exception as e:
        print(f"Error: {e}")
        return "⚠️ Calculation Error. Please try again."

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






