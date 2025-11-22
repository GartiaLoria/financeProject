import streamlit as st
import pandas as pd
import plotly.express as px
from utils import collection, get_chat_response

# --- CONFIGURATION ---
st.set_page_config(page_title="Expense Tracker", page_icon="💰", layout="wide")
CURRENCY = "₹" 

# --- DARK MODE CSS ---
st.markdown("""
<style>
    .metric-card {
        background-color: #262730;
        border: 1px solid #41424C;
        padding: 15px;
        border-radius: 10px;
        color: white;
    }
</style>
""", unsafe_allow_html=True)

st.title("💰 My Expenses")

# --- LOAD DATA ---
cursor = collection.find()
data = list(cursor)

if not data:
    st.warning("No data found. Use your Telegram bot to add expenses!")
else:
    # Clean Data
    df = pd.DataFrame(data)
    df['_id'] = df['_id'].astype(str)
    df['date'] = pd.to_datetime(df['date'])

    # --- FILTERS ---
    st.sidebar.header("Filters")
    df['Month'] = df['date'].dt.strftime('%B')
    df['Year'] = df['date'].dt.year
    
    unique_years = sorted(df['Year'].unique(), reverse=True)
    selected_year = st.sidebar.selectbox("Year", unique_years, index=0)
    df_year = df[df['Year'] == selected_year]
    
    available_months = df_year['Month'].unique()
    selected_month = st.sidebar.selectbox("Month", ["All"] + list(available_months))
    
    if selected_month != "All":
        df_filtered = df_year[df_year['Month'] == selected_month]
    else:
        df_filtered = df_year

    # --- METRICS ---
    total_spent = df_filtered['a'].sum()
    avg_spent = df_filtered['a'].mean() if not df_filtered.empty else 0
    
    col1, col2, col3 = st.columns(3)
    with col1: st.metric(label="Net Total", value=f"{CURRENCY}{total_spent:,.0f}")
    with col2: st.metric(label="Transactions", value=len(df_filtered))
    with col3: st.metric(label="Average / Txn", value=f"{CURRENCY}{avg_spent:,.0f}")

    st.divider()

    # --- CHARTS ---
    col_chart1, col_chart2 = st.columns(2)
    
    with col_chart1:
        st.subheader("Spending by Category")
        if not df_filtered.empty:
            fig_pie = px.pie(df_filtered, values='a', names='c', hole=0.5, color_discrete_sequence=px.colors.qualitative.Pastel)
            st.plotly_chart(fig_pie, width="stretch", key="pie_chart")

    with col_chart2:
        st.subheader("Spending Over Time")
        if not df_filtered.empty:
            daily_trend = df_filtered.groupby(df_filtered['date'].dt.date)['a'].sum().reset_index()
            fig_bar = px.bar(daily_trend, x='date', y='a', color='a', color_continuous_scale="Viridis")
            st.plotly_chart(fig_bar, width="stretch", key="trend_bar")

    # --- RECENT TRANSACTIONS LIST ---
    st.divider()
    st.subheader("📝 Recent Transactions")
    
    recent_tx = df_filtered.sort_values(by="date", ascending=False).head(10)
    
    for index, row in recent_tx.iterrows():
        with st.container():
            c1, c2, c3 = st.columns([1, 3, 1])
            
            # Date
            c1.write(f"**{row['date'].strftime('%d %b')}**")
            
            # Item + Note
            item = row.get('i', 'Unknown')
            category = row.get('c', 'General')
            note = row.get('n', "")
            
            c2.write(f"{item} ({category})")
            if note: c2.caption(f"📌 {note}")
            
            # Amount (Color Logic)
            amount = row.get('a', 0)
            if amount < 0:
                c3.markdown(f"<span style='color:#00FF00'>+ {CURRENCY}{abs(amount)}</span>", unsafe_allow_html=True)
            else:
                c3.write(f"{CURRENCY}{amount}")
                
            st.markdown("---")

    # --- AI CHAT ---
    with st.expander("🤖 Ask AI about your spending"):
        user_query = st.text_input("Ask a question...")
        if user_query:
            with st.spinner("Thinking..."):
                data_str = df_filtered.to_json(orient="records", date_format="iso")
                answer = get_chat_response(user_query, data_str)
                st.info(answer)