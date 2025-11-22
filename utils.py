import os
import google.generativeai as genai
from pymongo import MongoClient
from datetime import datetime
import json
import re
import certifi

# --- CONFIGURATION ---
# ⚠️ PASTE YOUR ACTUAL KEYS HERE
MONGO_URI = os.getenv("MONGO_URI")
GEMINI_KEY = os.getenv("GEMINI_KEY")

# --- SETUP ---
# We use certifi to prevent SSL errors on Windows
cluster = MongoClient(MONGO_URI, tlsCAFile=certifi.where())
db = cluster["expense_tracker"]
collection = db["expenses"]

genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-2.5-flash')

# --- FUNCTIONS ---

def clean_json_string(text):
    """
    Robust cleaner: Handles both Single Objects {} and Lists []
    """
    text = text.replace('```json', '').replace('```', '').strip()
    
    # If it looks like a list
    if text.startswith('['):
        start = text.find('[')
        end = text.rfind(']')
        if start != -1 and end != -1: return text[start:end+1]
    # If it looks like a single object
    else:
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1: return text[start:end+1]
        
    return text

def parse_expense_with_gemini(user_text):
    """
    Extracts transactions into a JSON LIST. 
    Looks for 'save c' to extract context notes.
    """
    prompt = f"""
    You are a Data Extraction API. 
    User Input: "{user_text}"
    
    Task: Extract ALL transactions into a JSON LIST.
    
    RULES for 'n' (Note/Context):
    - CHECK: Does input contain code "save c" or "context"?
    - IF YES: Extract description (e.g. "for dinner", "with team") into field 'n'.
    - IF NO: Field 'n' must be empty string "".
    
    RULES for 'c' (Category):
    - If user says "Owe", "Payable", "Give [Person]" (Future tense) -> Category is "Debt".
    - If user says "Lent", "Given" (Past tense) -> Category is "Loan Given".
    - Otherwise -> Normal Category (Food, Travel, etc).

    RULES for 'a' (Amount):
    - POSITIVE (+): Expense, Lending, Debt (Money leaves you).
    - NEGATIVE (-): Income, Repayment (Money comes to you).
    
    Output ONLY a JSON LIST:
    [
      {{"action": "add", "i": "Item", "a": 100, "c": "Category", "n": "note here"}}
    ]
    """
    try:
        response = model.generate_content(prompt)
        cleaned_text = clean_json_string(response.text)
        data = json.loads(cleaned_text)
        
        # Ensure it's always a list
        if isinstance(data, dict): data = [data]
            
        # Sanitize Data
        for entry in data:
            if 'i' in entry: entry['i'] = str(entry['i']).title()
            if 'c' in entry: entry['c'] = str(entry['c']).title()
            if 'a' in entry: entry['a'] = float(entry['a'])
            if 'n' not in entry: entry['n'] = "" # Default to empty note
            
        return data
    except Exception as e:
        print(f"Parsing Error: {e}")
        print(f"Raw Output: {response.text}")
        return None

def add_expense(data):
    entry = {
        "i": data['i'], 
        "a": data['a'], 
        "c": data['c'], 
        "n": data.get('n', ""), 
        "date": datetime.now()
    }
    collection.insert_one(entry)

def delete_expense(data):
    # Find entry matching amount and similar item name
    query = {"a": data['a'], "i": {"$regex": data['i'], "$options": "i"}}
    target = collection.find_one(query, sort=[("date", -1)])
    if target:
        collection.delete_one({"_id": target["_id"]})
        return True
    return False

def get_chat_response(query, user_data_context):
    prompt = f"""
    Context: {user_data_context}
    User Question: {query}
    Answer concisely. Use emojis. Do not use bold markdown (**).
    """
    response = model.generate_content(prompt)
    return response.text