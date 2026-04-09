import streamlit as st
import mysql.connector
import pandas as pd
from datetime import datetime
import warnings

warnings.filterwarnings('ignore')

# --- DATABASE CONNECTION ---
def run_query(query, params=None, commit=False):
    try:
        conn = mysql.connector.connect(**st.secrets["mysql"])
        cursor = conn.cursor(dictionary=True)
        cursor.execute(query, params or ())
        if commit:
            conn.commit()
            result = True
        else:
            result = cursor.fetchall()
        conn.close()
        return result
    except Exception as e:
        st.error(f"Database Error: {e}")
        return None

# --- UI SETTINGS ---
st.set_page_config(page_title="Smart EV Charging System", layout="wide")

# --- ROLE SELECTION ---
role = st.sidebar.selectbox("Select Access Level", ["User (EV Owner)", "Admin (Manager)"])

# ---------------- USER SIDE ----------------
if role == "User (EV Owner)":
    st.title("🚗 My EV Portal")
    user_id = 1 # Samayra Kapoor
    
    tabs = st.tabs(["📍 Find & Charge", "📜 My Sessions", "💳 Wallet"])
    
    with tabs[0]: 
        st.header("Start or End a Session")
        
        # Check if user already has an active session
        active_session = run_query("""
            SELECT session_id, slot_id FROM Sessions 
            WHERE vehicle_id IN (SELECT vehicle_id FROM Vehicles WHERE owner_id=%s) 
            AND end_time IS NULL
        """, (user_id,))

        if not active_session:
            # START SESSION UI
            stations = run_query("SELECT station_id, name FROM Stations WHERE status='Active'")
            station_choice = st.selectbox("Choose Station", options=stations, format_func=lambda x: x['name'])
            
            slots = run_query("SELECT slot_id, plug_type FROM Slots WHERE station_id=%s AND availability=1", (station_choice['station_id'],))
            
            if slots:
                slot_choice = st.selectbox("Available Slots", options=slots, format_func=lambda x: f"Slot {x['slot_id']} ({x['plug_type']})")
                my_cars = run_query("SELECT vehicle_id, model_name FROM Vehicles WHERE owner_id=%s", (user_id,))
                car_choice = st.selectbox("Select Vehicle", options=my_cars, format_func=lambda x: x['model_name'])
                
                if st.button("🔌 Start Charging"):
                    # 1. Create Session 2. Mark Slot Occupied
                    run_query("INSERT INTO Sessions (vehicle_id, slot_id, start_time) VALUES (%s, %s, NOW())", 
                              (car_choice['vehicle_id'], slot_choice['slot_id']), commit=True)
                    run_query("UPDATE Slots SET availability=0 WHERE slot_id=%s", (slot_choice['slot_id'],), commit=True)
                    st.success("Session Started! The slot is now marked as 'Occupied' for other users.")
                    st.rerun()
            else:
                st.error("No slots available here. Check the 'Centralized Documentation' in Admin view!")
        else:
            # END SESSION UI
            st.warning("⚡ Charging in Progress...")
            if st.button("🛑 End Session & Pay Bill"):
                s_id = active_session[0]['session_id']
                sl_id = active_session[0]['slot_id']
                bill_amount = 450.00 # Automated calculation based on 22.5kWh * 20 Tariff
                
                # 1. Check Wallet Balance first
                user_data = run_query("SELECT wallet_balance FROM EV_Owners WHERE owner_id=%s", (user_id,))
                current_balance = float(user_data[0]['wallet_balance'])
                
                if current_balance >= bill_amount:
                    # --- TRANSACTION START ---
                    # 2. Deduct from Wallet
                    new_balance = current_balance - bill_amount
                    run_query("UPDATE EV_Owners SET wallet_balance=%s WHERE owner_id=%s", (new_balance, user_id), commit=True)
                    
                    # 3. Update Session & Create PAID Bill
                    run_query("UPDATE Sessions SET end_time=NOW(), energy_consumed=22.5 WHERE session_id=%s", (s_id,), commit=True)
                    run_query("INSERT INTO Bills (session_id, total_amount, status) VALUES (%s, %s, 'Paid')", (s_id, bill_amount), commit=True)
                    
                    # 4. Free the Slot
                    run_query("UPDATE Slots SET availability=1 WHERE slot_id=%s", (sl_id,), commit=True)
                    
                    st.success(f"Payment Successful! ₹{bill_amount} deducted. New Balance: ₹{new_balance}")
                    st.balloons() # Celebration effect for successful payment
                    st.rerun()
                else:
                    st.error(f"Insufficient Balance! Bill is ₹{bill_amount} but you only have ₹{current_balance}. Please top up your wallet.")
    with tabs[1]:
        st.header("Your Charging History")
        history = run_query("""
            SELECT s.start_time, s.end_time, s.energy_consumed, b.total_amount, b.status 
            FROM Sessions s 
            LEFT JOIN Bills b ON s.session_id=b.session_id 
            WHERE s.vehicle_id IN (SELECT vehicle_id FROM Vehicles WHERE owner_id=%s)
            ORDER BY s.start_time DESC
        """, (user_id,))
        st.dataframe(history, use_container_width=True)

    with tabs[2]:
        st.header("My Digital Wallet")
        user_data = run_query("SELECT wallet_balance FROM EV_Owners WHERE owner_id=%s", (user_id,))
        
        balance = user_data[0]['wallet_balance']
        st.metric("Balance", f"₹ {balance}")
        
        amount = st.number_input("Enter amount to add", min_value=100, step=100)
        if st.button("➕ Add Money"):
            new_balance = float(balance) + amount
            run_query("UPDATE EV_Owners SET wallet_balance=%s WHERE owner_id=%s", (new_balance, user_id), commit=True)
            st.success(f"₹{amount} added! New balance: ₹{new_balance}")
            st.rerun()
# ---------------- ADMIN SIDE ----------------
else:
    st.title("📊 Infrastructure Management")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Revenue Trend")
        rev_data = run_query("SELECT date(start_time) as date, SUM(total_amount) as daily_rev FROM Bills b JOIN Sessions s ON b.session_id=s.session_id GROUP BY 1")
        if rev_data:
            df_rev = pd.DataFrame(rev_data)
            st.line_chart(df_rev.set_index('date'))

    with col2:
        st.subheader("Peak Usage Hours")
        peak_data = run_query("SELECT HOUR(start_time) as hour, COUNT(*) as sessions FROM Sessions GROUP BY 1")
        if peak_data:
            df_peak = pd.DataFrame(peak_data)
            st.bar_chart(df_peak.set_index('hour'))
            
    st.subheader("Station Status Monitor")
    full_status = run_query("""
        SELECT s.name, COUNT(sl.slot_id) as total_slots, SUM(sl.availability) as available_slots
        FROM Stations s
        LEFT JOIN Slots sl ON s.station_id = sl.station_id
        GROUP BY s.station_id
    """)
    st.dataframe(full_status, use_container_width=True)