import streamlit as st
import sqlite3
from datetime import datetime
from streamlit_autorefresh import st_autorefresh
import pandas as pd

# Set up the Streamlit page (must be the first command)
st.set_page_config(layout="wide")  # Use the full width of the screen

# Hide Streamlit menu, footer, and prevent code inspection
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .stDeployButton {display: none !important;}  /* Hide GitHub button */
    </style>

    <script>
    document.addEventListener('contextmenu', event => event.preventDefault());
    document.onkeydown = function(e) {
        if (e.ctrlKey && (e.keyCode === 85 || e.keyCode === 83)) {
            return false;  // Disable "Ctrl + U" (View Source) & "Ctrl + S" (Save As)
        }
        if (e.keyCode == 123) {
            return false;  // Disable "F12" (DevTools)
        }
    };
    </script>
    """, unsafe_allow_html=True)

# Custom CSS for better styling
st.markdown(
    """
    <style>
    /* General Styling */
    body {
        font-family: 'Arial', sans-serif;
        background-color: #f5f5f5;
    }
    @keyframes slide {
        0% { transform: translateX(0%); }
        100% { transform: translateX(-100%); }
    }
    /* Popup CSS */
    .popup {
        position: fixed;
        top: 20px;
        right: 20px;
        background-color: #4CAF50;
        color: white;
        padding: 15px;
        border-radius: 5px;
        box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
        z-index: 1000;
        animation: fadeInOut 3s ease-in-out;
    }
    @keyframes fadeInOut {
        0% { opacity: 0; }
        10% { opacity: 1; }
        90% { opacity: 1; }
        100% { opacity: 0; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------- CONFIG ----------
# Remove this
# TEAMS = ["Team A", "Team B", "Team C", "Team D"]
# STARTING_BUDGET = 100000
BID_INCREMENT = 5000

# ---------- DB SETUP ----------
conn = sqlite3.connect('biddi09i_game.db', check_same_thread=False)
c = conn.cursor()

# Create tables
c.execute('''CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    rating INTEGER,
    category TEXT,
    nationality TEXT,
    image_url TEXT,
    base_price INTEGER,
    is_active INTEGER DEFAULT 0,
    winner_team TEXT DEFAULT NULL,
    unsold_timestamp REAL DEFAULT 0
)''')

c.execute('''CREATE TABLE IF NOT EXISTS bids (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER,
    team_name TEXT,
    amount INTEGER,
    timestamp TEXT
)''')

# Create teams table with password column
c.execute('''CREATE TABLE IF NOT EXISTS teams (
    name TEXT PRIMARY KEY,
    budget_remaining INTEGER,
    logo_url TEXT,
    initial_budget INTEGER,
    password TEXT NOT NULL
)''')

# Add password column if it doesn't exist
try:
    c.execute("ALTER TABLE teams ADD COLUMN password TEXT NOT NULL DEFAULT ''")
except sqlite3.OperationalError:
    # Handle the case where the column already exists or other errors
    pass

# Check if unsold_timestamp column exists
try:
    c.execute("SELECT unsold_timestamp FROM items LIMIT 1")
except sqlite3.OperationalError:
    # Column doesn't exist, add it
    c.execute("ALTER TABLE items ADD COLUMN unsold_timestamp REAL DEFAULT 0")

# Create sold_items table
c.execute('''CREATE TABLE IF NOT EXISTS sold_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_name TEXT NOT NULL,
    sold_amount INTEGER,
    rating INTEGER,
    category TEXT,
    nationality TEXT,
    team_bought TEXT,
    timestamp TEXT
)''')

# Create unsold_items table
c.execute('''CREATE TABLE IF NOT EXISTS unsold_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_name TEXT NOT NULL,
    rating INTEGER,
    category TEXT,
    nationality TEXT,
    status TEXT,
    timestamp TEXT
)''')

conn.commit()

# Initialize teams if not present
# for team in TEAMS:
#     c.execute("INSERT OR IGNORE INTO teams (name, budget_remaining) VALUES (?, ?)", (team, STARTING_BUDGET))
conn.commit()

# ---------- FUNCTIONS ----------

def get_active_item():
    c.execute("SELECT * FROM items WHERE is_active = 1 LIMIT 1")
    return c.fetchone()

def get_highest_bid(item_id):
    c.execute("SELECT team_name, amount FROM bids WHERE item_id = ? ORDER BY amount DESC LIMIT 1", (item_id,))
    return c.fetchone()

def get_bid_increment(current_bid):
    """
    Returns bid increment based on current bid amount:
    - Up to ₹1 crore: ₹5 lakh increment
    - Up to ₹2 crore: ₹10 lakh increment
    - Between ₹2-5 crore: ₹20 lakh increment
    - Above ₹5 crore: ₹25 lakh increment
    """
    if current_bid < 10000000:  # Less than ₹1 crore
        return 500000  # ₹5 lakh
    elif current_bid < 20000000:  # Less than ₹2 crore
        return 1000000  # ₹10 lakh
    elif current_bid < 50000000:  # Less than ₹5 crore
        return 2000000  # ₹20 lakh
    else:  # Above ₹5 crore
        return 2500000  # ₹25 lakh

def place_bid(item_id, team_name, current_amount):
    # Check if the item is already sold
    c.execute("SELECT winner_team, base_price FROM items WHERE id = ?", (item_id,))
    item_details = c.fetchone()
    
    # Get the team's remaining budget
    remaining_budget = get_team_budget(team_name)

    # Check if this is the first bid
    c.execute("SELECT COUNT(*) FROM bids WHERE item_id = ?", (item_id,))
    bid_count = c.fetchone()[0]
    
    # If it's the first bid, use base price, otherwise add increment
    if bid_count == 0:
        new_amount = current_amount  # Use base price for first bid
    else:
        # Get the appropriate bid increment based on current amount
        increment = get_bid_increment(current_amount)
        new_amount = current_amount + increment

    # Check if the new bid amount exceeds the remaining budget
    if new_amount > remaining_budget:
        st.warning(f"{team_name} doesn't have enough budget to place this bid!")
        return  # Exit the function if the bid cannot be placed

    if item_details and item_details[0] != 'UNSOLD':
        previous_winner = item_details[0]
        previous_amount = item_details[1]
        
        # Refund the previous team
        update_team_budget(previous_winner, previous_amount)
        
        # Remove the item from sold_items table
        c.execute("DELETE FROM sold_items WHERE item_name = ?", (item_details[1],))

    c.execute("INSERT INTO bids (item_id, team_name, amount, timestamp) VALUES (?, ?, ?, ?)",
              (item_id, team_name, new_amount, datetime.now().isoformat()))
    c.execute("UPDATE items SET base_price = ? WHERE id = ?", (new_amount, item_id))
    conn.commit()

def get_team_budget(team_name):
    c.execute("SELECT budget_remaining FROM teams WHERE name = ?", (team_name,))
    result = c.fetchone()
    return result[0] if result else 0

def update_team_budget(team_name, spent_amount):
    c.execute("UPDATE teams SET budget_remaining = budget_remaining - ? WHERE name = ?", (spent_amount, team_name))
    conn.commit()

def get_all_items():
    c.execute("SELECT id, name, rating, category, nationality, image_url, base_price, is_active, winner_team FROM items")
    return c.fetchall()

def set_active_item(item_id):
    c.execute("UPDATE items SET is_active = 0")
    c.execute("UPDATE items SET is_active = 1, winner_team = NULL WHERE id = ?", (item_id,))
    conn.commit()

def stop_all_bidding():
    active = get_active_item()
    if active:
        item_id = active[0]
        highest = get_highest_bid(item_id)
        if highest:
            winner, amount = highest
            update_team_budget(winner, amount)
            c.execute("UPDATE items SET winner_team = ? WHERE id = ?", (winner, item_id))
            
            # Insert sold item into sold_items table
            c.execute("INSERT INTO sold_items (item_name, sold_amount, rating, category, nationality, team_bought, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?)",
                      (active[1], amount, active[2], active[3], active[4], winner, datetime.now().isoformat()))
            
            # Remove from unsold_items table
            c.execute("DELETE FROM unsold_items WHERE item_name = ?", (active[1],))
        
        c.execute("UPDATE items SET is_active = 0 WHERE id = ?", (item_id,))
        conn.commit()

def get_team_budgets():
    c.execute("SELECT name, budget_remaining, logo_url FROM teams")
    return c.fetchall()

def mark_as_unsold(item_id):
    # Set a timestamp for when the item was marked as unsold
    timestamp = datetime.now().timestamp()
    c.execute("UPDATE items SET winner_team = 'UNSOLD', is_active = 0, unsold_timestamp = ? WHERE id = ?", 
             (timestamp, item_id))
    
    # Get item details to insert into unsold_items table
    c.execute("SELECT name, rating, category, nationality FROM items WHERE id = ?", (item_id,))
    item_details = c.fetchone()
    
    if item_details:
        c.execute("INSERT INTO unsold_items (item_name, rating, category, nationality, status, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                  (item_details[0], item_details[1], item_details[2], item_details[3], 'Unsold', datetime.now().isoformat()))
    
    conn.commit()

def delete_item(item_id):
    # Fetch the item name before deletion
    c.execute("SELECT name FROM items WHERE id = ?", (item_id,))
    item_name = c.fetchone()
    
    if item_name:
        item_name = item_name[0]  # Get the actual name from the tuple

        # Delete from items table
        c.execute("DELETE FROM items WHERE id = ?", (item_id,))
        # Delete from bids table
        c.execute("DELETE FROM bids WHERE item_id = ?", (item_id,))
        # Delete from sold_items and unsold_items tables
        c.execute("DELETE FROM sold_items WHERE item_name = ?", (item_name,))
        c.execute("DELETE FROM unsold_items WHERE item_name = ?", (item_name,))
    
    conn.commit()

def get_team_squad_info(team_name):
    # Fetch players for the specified team
    c.execute("SELECT name, rating, category, nationality FROM items WHERE winner_team = ?", (team_name,))
    players = c.fetchall()

    # Initialize metrics
    total_spent = 0
    total_rating = 0
    remaining_budget = 0  # This will be fetched from the teams table
    num_batters = 0
    num_bowlers = 0
    num_allrounders = 0
    num_wicketkeepers = 0
    num_indian_players = 0
    num_foreign_players = 0

    # Calculate metrics
    for player in players:
        player_name, player_rating, player_category, player_nationality = player
        total_rating += player_rating

        # Fetch the sold amount for the player
        c.execute("SELECT sold_amount FROM sold_items WHERE item_name = ?", (player_name,))
        sold_amount_result = c.fetchone()
        if sold_amount_result:
            total_spent += sold_amount_result[0]  # Update total_spent with the sold amount

        # Count player categories
        if player_category == "Batsman":
            num_batters += 1
        elif player_category == "Bowler":
            num_bowlers += 1
        elif player_category == "Allrounder":
            num_allrounders += 1
        elif player_category == "Wicketkeeper":
            num_wicketkeepers += 1

        # Count nationality
        if player_nationality == "India":
            num_indian_players += 1
        else:
            num_foreign_players += 1

    # Fetch remaining budget for the team
    c.execute("SELECT budget_remaining FROM teams WHERE name = ?", (team_name,))
    budget_result = c.fetchone()  # Store the result in a variable
    remaining_budget = budget_result[0] if budget_result else 0  # Check the variable

    # Total number of players bought
    total_players_bought = len(players)

    return {
        "total_spent": total_spent,
        "total_rating": total_rating,
        "remaining_budget": remaining_budget,
        "num_batters": num_batters,
        "num_bowlers": num_bowlers,
        "num_allrounders": num_allrounders,
        "num_wicketkeepers": num_wicketkeepers,
        "num_indian_players": num_indian_players,
        "num_foreign_players": num_foreign_players,
        "total_players_bought": total_players_bought,
    }

def format_amount(amount):
    """
    Format amount in lakhs (L) or crores (Cr)
    Examples:
    - 5000000 -> 50L (50 lakhs)
    - 20000000 -> 2Cr (2 crores)
    - 22500000 -> 2.25Cr (2.25 crores)
    """
    if amount >= 10000000:  # 1 crore = 10000000
        crores = amount / 10000000
        return f"₹{crores:.2f} Cr"
    else:
        lakhs = amount / 100000
        return f"₹{lakhs:.0f}L"

def get_sold_amount(item_name):
    c.execute("SELECT sold_amount FROM sold_items WHERE item_name = ?", (item_name,))
    result = c.fetchone()
    return result[0] if result else 0

# ---------- SIDEBAR ADMIN ----------
st.sidebar.title("Admin Panel")
admin_password = st.sidebar.text_input("Admin Password", type="password")

# Check if the password is correct
if admin_password == "admin123":
    st.session_state['admin_authenticated'] = True  # Store authentication state
    st.sidebar.success("Authenticated as Admin")
else:
    if 'admin_authenticated' in st.session_state:
        st.sidebar.success("Already authenticated as Admin")
    else:
        st.sidebar.warning("Please enter the correct password.")

    # Add tabs for different admin functions
if 'admin_authenticated' in st.session_state and st.session_state['admin_authenticated']:
    admin_tab = st.sidebar.radio("Admin Functions", ["Manage Teams", "Manage Players"])
    
    if admin_tab == "Manage Teams":
        st.sidebar.subheader("Team Management")
        
        # Add Clear All Teams button
        if st.sidebar.button("🗑️ Clear All Teams", type="primary"):
            c.execute("DELETE FROM teams")
            conn.commit()
            st.sidebar.success("All teams have been removed.")
            st.rerun()
        
        # Add new team section
        st.sidebar.markdown("### Add New Team")
        new_team_name = st.sidebar.text_input("Team Name")
        team_budget = st.sidebar.number_input("Initial Budget", min_value=0, value=100000)
        team_logo_url = st.sidebar.text_input("Team Logo URL")
        team_password = st.sidebar.text_input("Team Password", type="password")  # New password input

        if st.sidebar.button("Add Team") and new_team_name and team_password:
            c.execute("INSERT OR REPLACE INTO teams (name, budget_remaining, logo_url, initial_budget, password) VALUES (?, ?, ?, ?, ?)",
                      (new_team_name, team_budget, team_logo_url, team_budget, team_password))
            conn.commit()
            st.sidebar.success(f"Team '{new_team_name}' added/updated with the specified password.")
        
        # Show existing teams
        st.sidebar.markdown("### Existing Teams")
        c.execute("SELECT name, budget_remaining, logo_url, initial_budget FROM teams")
        teams = c.fetchall()

        for team in teams:
            with st.sidebar.expander(f"Team: {team[0]}"):
                # Convert budget to crores
                current_budget = team[1] / 10000000  # Convert to crores
                initial_budget = team[3] / 10000000  # Convert to crores
                
                # Format the budget display
                budget_display = f"₹{current_budget:.2f} Cr"  # Format to two decimal places
                
                st.write(f"Current Budget: {budget_display}")
                st.write(f"Initial Budget: ₹{initial_budget:.2f} Cr")
                
                # Input fields for editing budget and logo
                new_budget = st.number_input(f"Edit Budget for {team[0]}", min_value=0.0, value=max(0.0, current_budget), format="%.2f")
                new_logo_url = st.text_input(f"Edit Logo URL for {team[0]}", value=team[2])
                
                if st.button(f"Update {team[0]}", key=f"update_{team[0]}"):
                    # Update the team in the database
                    c.execute("UPDATE teams SET budget_remaining = ?, logo_url = ? WHERE name = ?", 
                              (new_budget * 10000000, new_logo_url, team[0]))  # Convert back to original value
                    conn.commit()
                    st.success(f"Updated budget and logo for {team[0]}.")
                    st.rerun()
                if st.button(f"Delete {team[0]}", key=f"del_{team[0]}"):
                    c.execute("DELETE FROM teams WHERE name = ?", (team[0],))
                    conn.commit()
                    st.rerun()
    
    elif admin_tab == "Manage Players":
        # Existing player management code
        st.sidebar.subheader("Player Management")
        item_name = st.sidebar.text_input("New Item Name")
        item_rating = st.sidebar.text_input("Player Rating", value="50")
        item_category = st.sidebar.selectbox("Player Category", ["Batsman", "Bowler", "Allrounder", "Wicketkeeper"])
        item_nationality = st.sidebar.selectbox("Player Nationality", ["India", "Afghanistan", "Australia", "England","New Zealand", "South Africa","West Indies", "Other"])
        item_image_url = st.sidebar.text_input("Player Image URL")
        # Change the base price input to be in lakhs
        item_base_price = st.sidebar.number_input("Base Price (in Lakhs)", min_value=0.0, value=5.0, format="%.2f")

        if st.sidebar.button("Add Item") and item_name:
            try:
                item_rating_value = int(item_rating)
                # Convert base price from lakhs to actual amount
                base_price_amount = int(item_base_price * 100000)
                
                c.execute("INSERT INTO items (name, rating, category, nationality, image_url, base_price) VALUES (?, ?, ?, ?, ?, ?)",
                         (item_name, item_rating_value, item_category, item_nationality, item_image_url, base_price_amount))
                conn.commit()
                formatted_base_price = format_amount(base_price_amount)
                st.sidebar.success(f"Item '{item_name}' added with base price of {formatted_base_price}.")
            except ValueError:
                st.sidebar.error("Please enter a valid integer for the Player Rating.")

        st.sidebar.subheader("Activate Bidding")
        items = get_all_items()
        item_names = [item[1] for item in items]
        selected_item_name = st.sidebar.selectbox("Select Player to Activate Bidding", item_names)

        if selected_item_name:
            selected_item = next(item for item in items if item[1] == selected_item_name)
            
            # Delete button
            if st.sidebar.button("🗑️ Delete Player", type="primary"):
                delete_item(selected_item[0])
                st.sidebar.success(f"Player '{selected_item_name}' deleted.")
                st.rerun()
            
            # Unsold button
            if st.sidebar.button("❌ Mark as Unsold", type="secondary"):
                mark_as_unsold(selected_item[0])
                st.sidebar.success(f"Player '{selected_item_name}' marked as unsold.")
                st.rerun()
            
            if st.sidebar.button("Start Bidding"):
                set_active_item(selected_item[0])
                st.sidebar.success(f"Bidding started for '{selected_item_name}'")

            if st.sidebar.button("Stop Current Bidding"):
                stop_all_bidding()
                st.sidebar.success("Bidding stopped and winner updated.")

# ---------- MAIN UI ----------
st.title("💸 Real-Time Bidding Game")

# 🌀 Refresh page every second
st_autorefresh(interval=1000, key="refresh")

# Add custom CSS to make the app use full width and improve image styles
st.markdown("""
    <style>
        .main > div {
            max-width: 100%;
            padding-left: 5%;
            padding-right: 5%;
        }
        
        /* Team Grid Styles */
        .team-grid {
            display: flex;
            flex-direction: row;
            gap: 5px;  /* Reduced from 10px */
            padding: 0px;  /* Reduced from 10px */
            justify-content: center;  /* Center the cards */
            flex-wrap: wrap;
            margin: -5px;  /* Negative margin to offset padding */
        }
        .team-card {
            text-align: center;
            background: white;
            padding: 12px 10px 10px 10px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 8px;
            transition: all 0.3s cubic-bezier(.4,0,.2,1);
            position: relative;
            border-radius: 16px;
            border: 1.5px solid rgba(0,0,0,0.07);
            min-width: 80px;
            min-height: 120px;
        }
        .team-card:hover {
            transform: translateY(-4px) scale(1.04);
            box-shadow: 0 8px 24px rgba(26,115,232,0.10), 0 2px 8px rgba(0,0,0,0.10);
            border-color: #1a73e8;
        }
        .team-card img {
            width: 70px;
            height: 70px;
            object-fit: contain;
            border-radius: 12px;
            background: linear-gradient(145deg, #f8fafc 60%, #e3f0ff 100%);
            box-shadow: 0 2px 12px rgba(26,115,232,0.07);
            margin-bottom: 2px;
            margin-top: 2px;
            transition: transform 0.35s cubic-bezier(.4,0,.2,1), box-shadow 0.35s cubic-bezier(.4,0,.2,1);
        }
        .team-card:hover img {
            transform: scale(1.13) rotate(2deg);
            box-shadow: 0 8px 32px 0 rgba(26,115,232,0.18), 0 2px 8px rgba(0,0,0,0.10);
        }
        .team-name {
            font-size: 14px;  /* Reduced from 16px */
            font-weight: 800;
            color: #2c3e50;
            margin: 0;
            transition: color 0.3s ease;
        }
        .team-card:hover .team-name {
            color: #1a73e8;
        }
        .team-budget {
            font-size: 15px;
            font-weight: 900;
            color: #1a73e8;
            margin: 0;
            margin-top: 2px;
            margin-bottom: 2px;
            background: rgba(26,115,232,0.10);
            padding: 6px 7px;
            border-radius: 8px;
            letter-spacing: 0.5px;
            box-shadow: 0 1px 4px rgba(26,115,232,0.07);
            transition: all 0.3s cubic-bezier(.4,0,.2,1);
            display: inline-block;
            white-space: nowrap;
        }
        .team-card:hover .team-budget {
            transform: scale(1.08);
            color: #28a745;
            background: rgba(40,167,69,0.13);
            box-shadow: 0 2px 8px rgba(40,167,69,0.10);
        }

        /* Tab Styling */
        .stTabs {
            background: white;
            padding: 10px;
            border-radius: 15px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.05);
        }
        .stTabs [data-baseweb="tab-list"] {
            gap: 10px;
            background: #f8f9fa;
            padding: 10px;
            border-radius: 12px;
            border: 1px solid rgba(0,0,0,0.05);
        }
        .stTabs [data-baseweb="tab"] {
            height: 40px;
            padding: 0 20px;
            background: white;
            border-radius: 10px;
            color: #6c757d;
            font-weight: 500;
            transition: all 0.3s ease;
            border: 1px solid rgba(108,117,125,0.1);
            font-size: 14px;
        }
        .stTabs [data-baseweb="tab"]:hover {
            background: #f1f8ff;
            color: #1a73e8;
            transform: translateY(-1px);
            border-color: rgba(26,115,232,0.2);
        }
        .stTabs [aria-selected="true"] {
            background: #1a73e8 !important;
            color: white !important;
            font-weight: 600 !important;
            border-color: transparent !important;
            box-shadow: 0 2px 5px rgba(26,115,232,0.2);
        }
        
        /* Add subtle animation for tab content */
        .stTabContent {
            animation: fadeIn 0.3s ease-in-out;
        }
        @keyframes fadeIn {{
            from {{ opacity: 0; transform: translateY(5px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}
    </style>
    """, unsafe_allow_html=True)

# Fetch available teams from the database
c.execute("SELECT name, budget_remaining, password FROM teams")
available_teams = c.fetchall()

# Create a list of team names
team_names = [team[0] for team in available_teams]

# Create tabs for different sections
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "🎯 Bidding & Budgets", 
    "📊 Players Market", 
    "👥 Team Squad", 
    "📜 Auction History",
    "🌟 Special Bidding Zone"  # New tab
])

# Tab 1: Bidding & Budgets
with tab1:
    st.subheader("Team Budgets")
    team_budgets = get_team_budgets()
    cols = st.columns(len(team_budgets)) if team_budgets else st.columns(1)

    # Display teams in a grid
    st.markdown('<div class="team-grid">', unsafe_allow_html=True)
    for idx, (team, budget, logo_url) in enumerate(team_budgets):
        with cols[idx]:
            st.markdown(
                f"""
                <div class=\"team-card\">
                    <img src=\"{logo_url}\" alt=\"{team} logo\" />
                    <div class=\"team-name\">{team}</div>
                    <div class=\"team-budget\">{format_amount(budget)}</div>
                </div>
                """,
                unsafe_allow_html=True
            )
    st.markdown('</div>', unsafe_allow_html=True)

    # --- SLIDER MARQUEE SECTION ---
    # Fetch all bought players (winner_team not NULL or 'UNSOLD')
    c.execute("SELECT name, rating, nationality, winner_team FROM items WHERE winner_team IS NOT NULL AND winner_team != 'UNSOLD'")
    slider_players = c.fetchall()

    # Fetch team ratings (sum of player ratings per team)
    team_ratings = {}
    for team in team_names:
        c.execute("SELECT SUM(rating) FROM items WHERE winner_team = ?", (team,))
        total = c.fetchone()[0]
        team_ratings[team] = total if total else 0

    slider_items = []
    for name, rating, nationality, team in slider_players:
        plane = "✈️" if nationality != "India" else ""
        total_team_rating = team_ratings.get(team, 0)
        slider_items.append(f'<span class="slider-item">{name} {plane} ({rating}) | <span style="color:#007bff;">{team}</span> ({total_team_rating})</span>')

    if not slider_items:
        slider_html = '<span class="slider-item">No players have been bought yet.</span>'
    else:
        # Repeat to fill the marquee
        repeated = slider_items * (250 // max(1, len(slider_items)))
        slider_html = ''.join(repeated)

    # Add the slider CSS and HTML
    st.markdown('''
        <style>
        .slider-container {
            width: 100%;
            overflow: hidden;
            white-space: nowrap;
            background: #d0e7e7; /* Slightly darker background */
            color: #333; /* Dark text color */
            padding: 10px 0;
            border-radius: 10px;
            margin-bottom: 18px;
            position: relative;
            box-shadow: 0 2px 8px rgba(67, 233, 123, 0.08);
            font-size: 18px;
            font-weight: 600;
            letter-spacing: 0.5px;
        }
        .slider-content {
            display: inline-block;
            padding-left: 100vw;
            animation: slider-marquee 1800s linear infinite;
        }
        .slider-item {
            display: inline-block;
            margin-right: 40px;
            font-size: 18px;
            font-weight: bold;
            color: #1a1a1a; /* Darker text color for better contrast */
            background: #ffffff; /* White background for items */
            padding: 10px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1); /* Subtle shadow for depth */
            transition: background 0.3s ease;
        }
        .slider-item:hover {
            background: #e0f7fa; /* Light blue on hover */
        }
        @keyframes slider-marquee {
            0% { transform: translateX(0%); }
            100% { transform: translateX(-100%); }
        }
        </style>
        <div class="slider-container">
            <div class="slider-content">''' + slider_html + '''</div>
        </div>
    ''', unsafe_allow_html=True)
    # --- END SLIDER MARQUEE SECTION ---

    # --- RECENT 5 PLAYERS PANEL ---
    recent_players = []
    # Fetch the current active item
    active_item = get_active_item()
    if active_item:
        item_id, item_name, item_rating, item_category, item_nationality, item_image_url, item_base_price, is_active, winner, unsold_timestamp = active_item
        # Check if bidding is ongoing (no winner yet)
        c.execute("SELECT winner_team FROM items WHERE id = ?", (item_id,))
        winner_team = c.fetchone()[0]
        if winner_team is None:
            recent_players.append({
                'name': item_name,
                'status': 'bidding',
                'icon': '🔨',
                'amount': None,
                'team': None
            })
    # Fetch the last 4 finished bids (sold)
    c.execute("SELECT item_name, sold_amount, team_bought, timestamp FROM sold_items ORDER BY timestamp DESC LIMIT 4")
    sold = c.fetchall()

    # Fetch the last 4 unsold items
    c.execute("SELECT item_name, timestamp FROM unsold_items ORDER BY timestamp DESC LIMIT 4")
    unsold = c.fetchall()

    # Merge and sort by timestamp (most recent first)
    merged = []
    for s in sold:
        formatted_amount = format_amount(s[1])  # Format the sold amount
        merged.append({'name': s[0], 'status': 'sold', 'icon': '✅', 'amount': formatted_amount, 'team': s[2], 'ts': s[3]})
    for u in unsold:
        merged.append({'name': u[0], 'status': 'unsold', 'icon': '❌', 'amount': None, 'team': None, 'ts': u[1]})

    # Sort the merged list by timestamp
    merged = sorted(merged, key=lambda x: x['ts'], reverse=True)

    # Add up to 4 most recent entries to recent_players
    for entry in merged[:4]:
        recent_players.append(entry)

    # Always show 5 (pad with empty if needed)
    while len(recent_players) < 5:
        recent_players.append({'name': '', 'status': 'empty', 'icon': '', 'amount': None, 'team': None})
    # --- CSS for panel ---
    st.markdown('''
    <style>
    .recent-panel-row {
        display: flex;
        flex-direction: row;
        gap: 12px;
        margin-bottom: 18px;
        margin-top: 6px;
        justify-content: flex-start;
        flex-wrap: wrap;
    }
    .recent-card {
        min-width: 70px;
        max-width: 240px;
        min-height: 54px;
        background: #e3f0ff;
        border-radius: 10px;
        box-shadow: 0 2px 8px rgba(26,115,232,0.07);
        display: flex;
        flex-direction: column;
        align-items: flex-start;
        justify-content: center;
        padding: 8px 14px 8px 12px;
        font-family: inherit;
        position: relative;
        border: 2px solid #b6d6ff;
        transition: all 0.2s ease;
        flex-grow: 1;
    }
    .recent-card.sold {
        background: #eafff2;
        border-color: #b6f5d8;
    }
    .recent-card.unsold {
        background: #fff0f0;
        border-color: #ffb6b6;
    }
    .recent-card.bidding {
        background: #fffbe6;
        border-color: #ffe066;
    }
    .recent-card .recent-title {
        font-size: clamp(14px, 2vw, 15px);
        font-weight: 700;
        color: #222;
        margin-bottom: 2px;
        display: flex;
        align-items: center;
        gap: 6px;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        width: 100%;
    }
    .recent-card .recent-status {
        font-size: clamp(13px, 2vw, 14px);
        font-weight: 800;
        margin-top: 1px;
        letter-spacing: 0.2px;
        display: flex;
        align-items: center;
        width: 100%;
    }
    .recent-card.sold .recent-status {
        color: #28a745;
    }
    .recent-card.unsold .recent-status {
        color: #dc3545;
    }
    .recent-card.bidding .recent-status {
        color: #e67e22;
    }
    .recent-card .recent-team {
        font-size: clamp(12px, 2vw, 13px);
        color: #1a73e8;
        font-weight: 600;
        margin-left: 8px;
    }
    
    /* Responsive adjustments */
    @media (max-width: 1200px) {
        .recent-panel-row {
            gap: 10px;
        }
        .recent-card {
            min-width: 160px;
            padding: 6px 12px 6px 10px;
        }
    }
    
    @media (max-width: 992px) {
        .recent-panel-row {
            gap: 8px;
            margin-bottom: 14px;
        }
        .recent-card {
            min-width: 140px;
            min-height: 50px;
        }
    }
    
    @media (max-width: 768px) {
        .recent-panel-row {
            gap: 6px;
            margin-bottom: 12px;
        }
        .recent-card {
            min-width: 120px;
            min-height: 46px;
            padding: 5px 10px 5px 8px;
        }
        .recent-card .recent-title {
            font-size: 13px;
            gap: 4px;
        }
        .recent-card .recent-status {
            font-size: 12px;
        }
    }
    
    @media (max-width: 576px) {
        .recent-panel-row {
            gap: 4px;
        }
        .recent-card {
            min-width: calc(50% - 8px);
            min-height: 42px;
        }
    }
    
    /* Hover effects */
    .recent-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 12px rgba(26,115,232,0.12);
    }
    .recent-card.sold:hover {
        box-shadow: 0 4px 12px rgba(40,167,69,0.12);
    }
    .recent-card.unsold:hover {
        box-shadow: 0 4px 12px rgba(220,53,69,0.12);
    }
    .recent-card.bidding:hover {
        box-shadow: 0 4px 12px rgba(230,126,34,0.12);
    }
    </style>
''', unsafe_allow_html=True)


    # Bidding section
    active_item = get_active_item()

    if not active_item:
        st.warning("No item is currently open for bidding.")
    else:
        item_id, item_name, item_rating, item_category, item_nationality, item_image_url, item_base_price, is_active, winner, unsold_timestamp = active_item
        
        # Display the player's name at the top
        st.header(f"🟢 {item_name}")

        # Create three columns for image, current highest bid, and current bidder
        cols = st.columns([1, 1, 1, 1])  # Equal width columns with no gap

        # Player Image Section
        with cols[0]:
            st.markdown(
                f"""
                <div style="
                    width: 100%;
                    padding: 0;
                    border: 1px solid rgba(0,0,0,0.1);
                    border-radius: 16px;
                    background: linear-gradient(145deg, #ffffff, #f8f9fa);
                    text-align: center;
                    box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
                    margin: 0;
                    height: 280px;
                    display: flex;
                    flex-direction: column;
                    justify-content: center;
                    align-items: center;
                    position: relative;
                    overflow: hidden;
                ">
                    <div class="image-container" style="
                        width: 200px;
                        height: 220px;
                        overflow: hidden;
                        border-radius: 16px;
                        position: relative;
                        box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
                    ">
                        <img src="{item_image_url}" 
                            style="
                                width: 100%;
                                height: 100%;
                                object-fit: cover;
                                transition: transform 0.5s cubic-bezier(0.4, 0, 0.2, 1);
                                border-radius: 16px;
                            "
                        />
                        <div style="
                            position: absolute;
                            bottom: 0;
                            left: 0;
                            right: 0;
                            padding: 0;
                            background: linear-gradient(to top, 
                                rgba(0,0,0,0.9) 0%,
                                rgba(0,0,0,0.7) 50%,
                                transparent 100%);
                            transition: all 0.3s ease;
                        ">
                            <p style="
                                margin: 0;
                                color: white;
                                font-weight: 600;
                                font-size: 20px;
                                text-shadow: 0 2px 4px rgba(0,0,0,0.3);
                                transform: translateY(0);
                                transition: transform 0.3s ease;
                            ">{item_name}</p>
                        </div>
                    </div>
                </div>
                <style>
                    .image-container:hover {{
                        transform: translateY(-5px);
                        box-shadow: 
                            0 20px 25px rgba(0, 0, 0, 0.15),
                            0 10px 10px rgba(0, 0, 0, 0.08);
                    }}
                    .image-container:hover img {{
                        transform: scale(1.05);
                    }}
                    .image-container:hover p {{
                        transform: translateY(-5px);
                    }}
                </style>
                """,
                unsafe_allow_html=True
            )

        # Get the highest bid
        highest = get_highest_bid(item_id)
        current_bid = highest[1] if highest else item_base_price
        current_team = highest[0] if highest else "No bids yet"

        # Current Highest Bid Section
        with cols[1]:
            current_bid_display = format_amount(current_bid)
            st.markdown(
                f"""
                <div style="
                    width: 100%;
                    padding: 10px;
                    border: 1px solid rgba(26, 115, 232, 0.2);
                    border-radius: 16px;
                    background: linear-gradient(145deg, #f0f8ff, #e0f7fa);
                    text-align: center;
                    box-shadow: 0 4px 6px rgba(26, 115, 232, 0.1);
                    height: 280px;
                    display: flex;
                    flex-direction: column;
                    justify-content: space-between;
                    position: relative;
                    overflow: hidden;
                ">
                    <div class="current-bid-header">
                        <h4 style="
                            margin: 0;
                            font-size: 22px;
                            font-weight: 700;
                            color: #1a73e8;
                        ">{'Current Bid' if highest else 'Base Price'}</h4>
                    </div>
                    <div class="current-bid-amount">
                        <span style="white-space: nowrap;">{current_bid_display}</span>
                    </div>
                    <div class="current-bid-details">
                        <div class="current-bid-detail">
                            <span class="current-bid-label">Rating</span>
                            <span class="current-bid-value">{item_rating}/100</span>
                        </div>
                        <div class="current-bid-detail">
                            <span class="current-bid-label">Category</span>
                            <span class="current-bid-value">{item_category}</span>
                        </div>
                        <div class="current-bid-detail">
                            <span class="current-bid-label">Nationality</span>
                            <span class="current-bid-value">{item_nationality}</span>
                        </div>
                    </div>
                </div>
                <style>
                    .current-bid-container {{
                        width: 100%;
                        padding: 10px;
                        border: 1px solid rgba(26, 115, 232, 0.2);
                        border-radius: 20px;
                        background: linear-gradient(145deg, #f0f8ff, #e0f7fa);
                        text-align: center;
                        box-shadow: 
                            0 4px 6px rgba(26, 115, 232, 0.1),
                            0 10px 15px rgba(26, 115, 232, 0.2);
                        height: 280px;
                        display: flex;
                        flex-direction: column;
                        justify-content: space-between;
                        position: relative;
                        overflow: hidden;
                        backdrop-filter: blur(10px);
                        transition: transform 0.3s ease;
                    }}

                    .current-bid-header {{
                        background: rgba(26, 115, 232, 0.1);
                        padding: 8px;
                        border-radius: 12px;
                        border: 1px solid rgba(26, 115, 232, 0.2);
                        height: 40px;
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        transition: background 0.3s ease;
                    }}

                    .current-bid-header:hover {{
                        background: rgba(26, 115, 232, 0.15);
                    }}

                    .current-bid-amount {{
                        font-size: 28px;
                        font-weight: 800;
                        color: #1a73e8;
                        background: white;
                        padding: 8px;
                        border-radius: 12px;
                        box-shadow: 
                            0 4px 6px rgba(26, 115, 232, 0.1),
                            0 10px 15px rgba(26, 115, 232, 0.2);
                        position: relative;
                        overflow: hidden;
                        border: 1px solid rgba(26, 115, 232, 0.2);
                        height: 60px;
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        transition: transform 0.3s ease;
                    }}

                    .current-bid-amount:hover {{
                        transform: scale(1.05);
                    }}

                    .current-bid-details {{
                        display: grid;
                        gap: 8px;
                        text-align: left;
                    }}

                    .current-bid-detail {{
                        padding: 8px;
                        background: rgba(26, 115, 232, 0.04);
                        border-radius: 10px;
                        display: flex;
                        align-items: center;
                        justify-content: space-between;
                        transition: all 0.3s ease;
                    }}

                    .current-bid-detail:hover {{
                        background: rgba(26, 115, 232, 0.06);
                    }}

                    .current-bid-label {{
                        font-weight: 600;
                        color: #1a73e8;
                    }}

                    .current-bid-value {{
                        color: #2c3e50;
                        font-weight: 500;
                    }}
                </style>
                """,
                unsafe_allow_html=True
            )

        # Current Bidder Section
        with cols[2]:
            current_timestamp = datetime.now().timestamp()
            c.execute("SELECT unsold_timestamp FROM items WHERE id = ?", (item_id,))
            unsold_timestamp = c.fetchone()[0] or 0
            show_unsold = (current_timestamp - unsold_timestamp) < 5 if unsold_timestamp else False

            if show_unsold:
                st.markdown(
                    f"""
                    <div style="
                        width: 100%;
                        padding: 20px;
                        border: 1px solid rgba(220,53,69,0.1);
                        border-radius: 24px;
                        background: linear-gradient(145deg, #fff5f5, #ffe6e6);
                        text-align: center;
                        box-shadow: 
                            0 4px 6px rgba(220, 53, 69, 0.02),
                            0 10px 15px rgba(220, 53, 69, 0.03),
                            0 20px 30px rgba(220, 53, 69, 0.04);
                        height: 320px;
                        display: flex;
                        flex-direction: column;
                        justify-content: center;
                        align-items: center;
                        position: relative;
                        overflow: hidden;
                        backdrop-filter: blur(10px);
                        -webkit-backdrop-filter: blur(10px);
                    ">
                        <div style="
                            width: 140px;
                            height: 140px;
                            background: white;
                            border-radius: 70px;
                            padding: 20px;
                            box-shadow: 
                                0 10px 20px rgba(220, 53, 69, 0.1),
                                0 6px 6px rgba(220, 53, 69, 0.06);
                            display: flex;
                            align-items: center;
                            justify-content: center;
                            margin: 10px 0;
                            position: relative;
                            animation: float 3s ease-in-out infinite;
                        ">
                            <div style="
                                position: absolute;
                                inset: 5px;
                                border-radius: 50%;
                                border: 2px solid rgba(220,53,69,0.2);
                                animation: pulse 2s ease-in-out infinite;
                            "></div>
                            <span style="
                                font-size: 50px;
                                transform: scale(1);
                                transition: transform 0.3s ease;
                            ">❌</span>
                        </div>
                        <p style="
                            margin: 20px 0 0 0;
                            font-weight: 700;
                            background: linear-gradient(135deg, #dc3545, #c82333);
                            -webkit-background-clip: text;
                            -webkit-text-fill-color: transparent;
                            font-size: 24px;
                            font-family: system-ui, -apple-system, sans-serif;
                            letter-spacing: 1px;
                        ">UNSOLD</p>
                    </div>
                    <style>
                        @keyframes float {{
                            0%, 100% {{ transform: translateY(0); }}
                            50% {{ transform: translateY(-10px); }}
                        }}
                        @keyframes pulse {{
                            0% {{ transform: scale(1); opacity: 1; }}
                            50% {{ transform: scale(1.1); opacity: 0.5; }}
                            100% {{ transform: scale(1); opacity: 1; }}
                        }}
                    </style>
                    """,
                    unsafe_allow_html=True
                )
            elif current_team == "No bids yet":
                st.markdown(
                    f"""
                    <div style="
                        width: 100%;
                        padding: 10px;
                        border: 1px solid rgba(108,117,125,0.1);
                        border-radius: 16px;
                        background: linear-gradient(145deg, #f8f9fa, #e9ecef);
                        text-align: center;
                        box-shadow: 0 4px 6px rgba(108, 117, 125, 0.1);
                        height: 280px;
                        display: flex;
                        flex-direction: column;
                        justify-content: center;
                        align-items: center;
                        position: relative;
                        overflow: hidden;
                    ">
                        <div class="waiting-circle" style="
                            width: 140px;
                            height: 140px;
                            background: white;
                            border-radius: 70px;
                            padding: 20px;
                            box-shadow: 0 4px 8px rgba(108, 117, 125, 0.1);
                            display: flex;
                            align-items: center;
                            justify-content: center;
                            position: relative;
                            margin: 10px 0;
                        ">
                            <div class="pulse-ring" style="
                                position: absolute;
                                inset: -3px;
                                border-radius: 50%;
                                border: 3px solid rgba(108,117,125,0.2);
                                animation: pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite;
                            "></div>
                            <div class="pulse-ring" style="
                                position: absolute;
                                inset: -6px;
                                border-radius: 50%;
                                border: 3px solid rgba(108,117,125,0.15);
                                animation: pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite 0.5s;
                            "></div>
                            <span style="
                                font-size: 50px;
                                color: #6c757d;
                                position: relative;
                                z-index: 1;
                                animation: bounce 2s ease infinite;
                            ">🤝</span>
                        </div>
                        <div style="
                            margin-top: 20px;
                            background: white;
                            padding: 12px;
                            border-radius: 16px;
                            box-shadow: 0 4px 8px rgba(108,117,125,0.1);
                            width: 80%;
                        ">
                            <p style="
                                margin: 0;
                                font-weight: 600;
                                background: linear-gradient(135deg, #6c757d, #495057);
                                -webkit-background-clip: text;
                                -webkit-text-fill-color: transparent;
                                font-size: 18px;
                                font-family: system-ui, -apple-system, sans-serif;
                                letter-spacing: 0.5px;
                                line-height: 1.2;
                                padding: 2px 10px;
                            ">Waiting for Bids</p>
                        </div>
                    </div>
                    <style>
                        @keyframes pulse {{
                            0% {{ transform: scale(1); opacity: 1; }}
                            50% {{ transform: scale(1.1); opacity: 0.5; }}
                            100% {{ transform: scale(1); opacity: 1; }}
                        }}
                        @keyframes bounce {{
                            0%, 100% {{ transform: translateY(0); }}
                            50% {{ transform: translateY(-10px); }}
                        }}
                        .waiting-circle:hover {{
                            transform: scale(1.05);
                            transition: transform 0.3s ease;
                        }}
                        .waiting-circle:hover .pulse-ring {{
                            animation-duration: 1.5s;
                        }}
                    </style>
                    """,
                    unsafe_allow_html=True
                )
            else:
                c.execute("SELECT logo_url FROM teams WHERE name = ?", (current_team,))
                team_logo_result = c.fetchone()
                team_logo_url = team_logo_result[0] if team_logo_result else ""
                
                st.markdown(
                    f"""
                    <div style="
                        width: 100%;
                        padding: 10px;
                        border: 1px solid rgba(40,167,69,0.1);
                        border-radius: 16px;
                        background: linear-gradient(145deg, #f8fff9, #e8f5e9);
                        text-align: center;
                        box-shadow: 0 4px 6px rgba(40, 167, 69, 0.1);
                        height: 280px;
                        display: flex;
                        flex-direction: column;
                        justify-content: center;
                        align-items: center;
                        position: relative;
                        overflow: hidden;
                    ">
                        <div class="bidder-circle" style="
                            width: 140px;
                            height: 140px;
                            background: white;
                            border-radius: 70px;
                            padding: 20px;
                            box-shadow: 0 4px 8px rgba(40, 167, 69, 0.1);
                            display: flex;
                            align-items: center;
                            justify-content: center;
                            position: relative;
                            margin: 10px 0;
                            transition: transform 0.3s ease;
                        ">
                            <div class="paddle-effect" style="
                                position: absolute;
                                inset: -3px;
                                border-radius: 50%;
                                border: 3px solid rgba(40,167,69,0.3);
                                animation: paddle 1.5s ease-in-out infinite;
                            "></div>
                            <img src="{team_logo_url}" 
                                class="team-logo"
                                style="
                                    max-width: 100%;
                                    max-height: 100%;
                                    object-fit: contain;
                                    transition: transform 0.3s ease;
                                "
                            />
                        </div>
                        <div style="
                            margin-top: 20px;
                            background: white;
                            padding: 12px;
                            border-radius: 16px;
                            box-shadow: 0 4px 8px rgba(40,167,69,0.1);
                            width: 80%;
                        ">
                            <div style="
                                font-weight: 600;
                                background: linear-gradient(135deg, #28a745, #218838);
                                -webkit-background-clip: text;
                                -webkit-text-fill-color: transparent;
                                font-size: 18px;
                                font-family: system-ui, -apple-system, sans-serif;
                                letter-spacing: 0.5px;
                                line-height: 1.2;
                                padding: 2px 10px;
                                white-space: nowrap;
                                overflow: hidden;
                                text-overflow: ellipsis;
                            ">{current_team}</div>
                        </div>
                    </div>
                    <style>
                        @keyframes paddle {{
                            0% {{ transform: scale(1) rotate(0deg); }}
                            25% {{ transform: scale(1.1) rotate(90deg); }}
                            50% {{ transform: scale(1) rotate(180deg); }}
                            75% {{ transform: scale(1.1) rotate(270deg); }}
                            100% {{ transform: scale(1) rotate(360deg); }}
                        }}
                        .bidder-circle:hover {{
                            transform: scale(1.05);
                        }}
                        .bidder-circle:hover .team-logo {{
                            transform: scale(1.1);
                        }}
                        .bidder-circle:hover .paddle-effect {{
                            animation-duration: 1s;
                            border-width: 4px;
                        }}
                    </style>
                    """,
                    unsafe_allow_html=True
                )

        # Initialize a session state variable to track the number of bids placed
        if 'bid_count' not in st.session_state:
            st.session_state['bid_count'] = 0

        # Recent Bids and Status Section (Column 4)
        with cols[3]:
            # First part - Recent Bids
            st.markdown(
                f"""
                <div style="
                    width: 100%;
                    border: 1px solid rgba(40, 167, 69, 0.2);
                    border-radius: 16px;
                    background: linear-gradient(145deg, #f0fff4, #e8f5e9);
                    text-align: center;
                    box-shadow: 0 4px 6px rgba(40, 167, 69, 0.1);
                    height: 50px;
                    display: flex;
                    flex-direction: column;
                    position: relative;
                    overflow: hidden;
                    margin-bottom: 10px;
                ">
                    <div style="
                        padding: 8px;
                        margin-bottom: 5px;
                        border-bottom: 1px solid rgba(40, 167, 69, 0.1);
                    ">
                        <h4 style="
                            margin: 0;
                            font-size: 20px;
                            font-weight: 700;
                            color: #28a745;
                        ">Recent Sold</h4>
                    </div>
                    <div style="
                        flex: 1;
                        display: flex;
                        flex-direction: column;
                        padding: 5px;
                        overflow-y: auto;
                    ">
                """,
                unsafe_allow_html=True
            )
            
            # Fetch recent bids for this item
            c.execute("SELECT team_name, amount, timestamp FROM bids WHERE item_id = ? ORDER BY timestamp DESC LIMIT 2", (item_id,))
            recent_bids = c.fetchall()

            # Fetch and display the four most recent sold items
            c.execute("SELECT item_name, team_bought, sold_amount FROM sold_items ORDER BY timestamp DESC LIMIT 4")
            recent_sold_items = c.fetchall()

            # Calculate how many items to show
            total_items = len(recent_bids) + len(recent_sold_items)
            
            # Determine how many recent bids and sold items to show
            bids_to_show = recent_bids[:max(0, 4 - len(recent_sold_items))]
            sold_to_show = recent_sold_items[:max(0, 4 - len(bids_to_show))]

            # Display recent bids
            for bid in bids_to_show:
                team, amount, timestamp = bid
                formatted_amount = format_amount(amount)
                st.markdown(
                    f"""
                    <div class="bid-card" style="
                        background: #fff;
                        padding: 11.5px;
                        border-radius: 10px;
                        border: 1px solid rgba(40, 167, 69, 0.2);
                        display: flex;
                        justify-content: space-between;
                        align-items: center;
                        box-shadow: 0 2px 4px rgba(40, 167, 69, 0.1);
                        margin-bottom: 8px;
                    ">
                        <div style="
                            display: flex;
                            align-items: center;
                            gap: 5px;
                            font-weight: 600;
                            color: #1a73e8;
                        ">
                            {team}
                        </div>
                        <div style="
                            display: flex;
                            align-items: center;
                            gap: 5px;
                        ">
                            <span style="color: #28a745; font-weight: 600;">{formatted_amount}</span>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )

            # Display recent sold items
            for item_name, team_bought, sold_amount in sold_to_show:
                # Truncate item name to a maximum of 12 characters, ensuring at least 10 characters are visible
                if len(item_name) > 12:
                    truncated_item_name = item_name[:12] + ''
                else:
                    truncated_item_name = item_name  # Show the full name if it's 12 characters or less

                # Ensure the item name is displayed in a single line
                formatted_amount = format_amount(sold_amount) if sold_amount else ""  # Format the sold amount if available
                st.markdown(
                    f"""
                    <div style="
                        display: flex;
                        justify-content: space-between;
                        align-items: center;
                        padding: 11px;
                        border: 1px solid rgba(40, 167, 69, 0.3);
                        border-radius: 12px;
                        background: linear-gradient(145deg, #e8f5e9, #f0fff4);
                        margin-bottom: 7px;
                        margin-top: 0;
                        white-space: nowrap;  /* Prevent line breaks */
                        overflow: hidden;     /* Hide overflow */
                        text-overflow: ellipsis; /* Add ellipsis for overflow */
                    ">
                        <div style="
                            font-size: 16px;
                            font-weight: 600;
                            color: #1a73e8;
                            flex-grow: 1;
                        ">{truncated_item_name}</div>
                        <div style="
                            display: flex;
                            align-items: center;
                            gap: 5px;
                            font-size: 16px;
                            font-weight: 600;
                            color: #28a745;
                            text-align: right;
                        ">
                            <span>{team_bought}</span>
                            <span>{formatted_amount}</span>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )

            if not bids_to_show and not sold_to_show:
                st.markdown(
                    """
                    <div style="
                        padding: 10px;
                        color: #6c757d;
                        font-style: italic;
                    ">
                        No recent bids or sold items.
                    </div>
                    """,
                    unsafe_allow_html=True
                )

    # Check if admin is authenticated
    if 'admin_authenticated' not in st.session_state or not st.session_state['admin_authenticated']:
        # Show Select Team and password input fields
        selected_team = st.selectbox("Select Team", team_names)

        # Find the selected team's details
        selected_team_details = next((team for team in available_teams if team[0] == selected_team), None)

        if selected_team_details:
            # Ensure that selected_team_details has the expected number of values
            if len(selected_team_details) == 3:
                team_name, budget, password = selected_team_details
                password_verified = False

                # Password input field
                password_input = st.text_input(f"Enter password for {team_name}", type="password")

                # Check if the password is correct
                if password_input == password:
                    st.session_state['team_password'] = password  # Store the password in session state
                    st.session_state['selected_team'] = team_name  # Store the selected team
                    password_verified = True

                # Only show bid button if password is verified
                if password_verified:
                    # Create a button using Streamlit's button function
                    if st.button(f"Bid ({team_name})"):
                        if budget < current_bid + BID_INCREMENT:
                            st.warning(f"{team_name} doesn't have enough budget!")
                        else:
                            place_bid(item_id, team_name, current_bid)
                            formatted_amount = format_amount(current_bid)
                            st.success(f"Bid placed by {team_name} for {formatted_amount}.")
                            st.session_state['selected_team'] = team_name  # Store the selected team in session state
                            st.rerun()
            else:
                st.warning("Team details are incomplete. Please check the database.")
        else:
            st.warning("Selected team not found. Please select a valid team.")


# Tab 2: Players Market
with tab2:
    st.subheader("Players Market")
    
    # Add dropdown to select which table to view
    market_view = st.selectbox(
        "Select View",
        ["Players Sold", "Players Unsold"],
        key="market_view"
    )
    
    # Show the selected table based on dropdown choice
    if market_view == "Players Sold":
        # Update the SQL query to change the order of columns
        c.execute("SELECT item_name, rating, category, nationality, sold_amount, team_bought FROM sold_items ORDER BY timestamp DESC")
        sold_items = c.fetchall()

        if sold_items:
            st.markdown("""
                <style>
                    .sold-table {
                        margin-top: 20px;
                        border-radius: 10px;
                        overflow: hidden;
                        box-shadow: 0 4px 12px rgba(0,0,0,0.1);
                    }
                </style>
            """, unsafe_allow_html=True)
            
            # Convert the sold amounts to the formatted version
            formatted_sold_items = []
            for item in sold_items:
                formatted_item = list(item)
                formatted_item[4] = format_amount(item[4])  # Format the sold_amount
                formatted_sold_items.append(formatted_item)
            
            sold_df = pd.DataFrame(
                formatted_sold_items,
                columns=["Player Name", "Rating", "Category", "Nationality", "Sold Amount", "Team Bought"]
            )
            st.dataframe(
                sold_df,
                use_container_width=True,
                height=400,
                hide_index=True
            )
        else:
            st.info("No players have been sold yet.")
    
    else:  # Players Unsold view
        # Update the query to include base_price
        c.execute("""
            SELECT i.name AS item_name, i.rating, i.category, i.nationality, i.base_price, 'Unsold' AS status 
            FROM items i 
            WHERE i.is_active = 0 AND i.winner_team = 'UNSOLD'
            ORDER BY i.unsold_timestamp DESC
        """)
        unsold_items = c.fetchall()

        if unsold_items:
            st.markdown("""
                <style>
                    .unsold-table {
                        margin-top: 20px;
                        border-radius: 10px;
                        overflow: hidden;
                        box-shadow: 0 4px 12px rgba(0,0,0,0.1);
                    }
                </style>
            """, unsafe_allow_html=True)
            
            # Update the DataFrame to include the base price
            formatted_unsold_items = []
            for item in unsold_items:
                formatted_item = list(item)
                formatted_item[4] = format_amount(item[4])  # Format the base_price
                formatted_unsold_items.append(formatted_item)
            
            unsold_df = pd.DataFrame(
                formatted_unsold_items,
                columns=["Player Name", "Rating", "Category", "Nationality", "Base Price", "Status"]
            )
            st.dataframe(
                unsold_df,
                use_container_width=True,
                height=400,
                hide_index=True
            )
        else:
            st.info("No players are currently unsold.")

# Tab 3: Team Squad
with tab3:
    st.subheader("Team Squad")
    
    # Dropdown for team selection
    selected_team_name = st.selectbox("Select Team", team_names, key="squad_team_select")

    # After the team selection, display the squad information
    if selected_team_name:
        team_info = get_team_squad_info(selected_team_name)

        # Create two columns for the information display
        col1, col2 = st.columns(2)
        
        with col1:
            st.write(f"Total Spend Amount: {format_amount(team_info['total_spent'])}")
            st.write(f"Total Rating: {team_info['total_rating']}")
            st.write(f"Remaining Budget: {format_amount(team_info['remaining_budget'])}")
            st.write(f"Total Players Bought: {team_info['total_players_bought']}")
        
        with col2:
            st.write(f"Batters: {team_info['num_batters']}")
            st.write(f"Bowlers: {team_info['num_bowlers']}")
            st.write(f"Allrounders: {team_info['num_allrounders']}")
            st.write(f"Wicketkeepers: {team_info['num_wicketkeepers']}")
            st.write(f"Indian Players: {team_info['num_indian_players']}")
            st.write(f"Foreign Players: {team_info['num_foreign_players']}")

        # Fetch and display the squad in a table
        c.execute("SELECT name, rating, category, nationality FROM items WHERE winner_team = ?", (selected_team_name,))
        players = c.fetchall()

        if players:
            players_df = pd.DataFrame(players, columns=["Player Name", "Rating", "Category", "Nationality"])
            st.dataframe(players_df)
        else:
            st.write("No players found for this team.")
    else:
        st.warning("Please select a team to view the squad information.")

# Tab 4: Auction History
with tab4:
    st.subheader("Auction History")
    
    # Fetch sold items ordered by timestamp in descending order
    c.execute("SELECT item_name, team_bought FROM sold_items ORDER BY timestamp DESC")
    sold_items = c.fetchall()

    # Fetch unsold items ordered by timestamp in descending order
    c.execute("SELECT item_name FROM unsold_items ORDER BY timestamp DESC")
    unsold_items = c.fetchall()

    # Display sold items
    for item in sold_items:
        st.write(f"✅ **{item[0]}** SOLD TO **{item[1]}**")

    # Display unsold items
    for item in unsold_items:
        st.write(f"❌ **{item[0]}** UNSOLD (No Team is interested)")

# Tab 5: Special Bidding Zone
with tab5:
    st.subheader("Special Bidding Zone")
    
    # Fetch the current active item
    active_item = get_active_item()
    
    if active_item:
        item_id, item_name, item_rating, item_category, item_nationality, item_image_url, item_base_price, is_active, winner, unsold_timestamp = active_item
        
        # Fetch the highest bid for the current item
        highest_bid = get_highest_bid(item_id)
        
        if highest_bid:
            current_bidder, current_bid_amount = highest_bid
        else:
            current_bidder = "No bids yet"
            current_bid_amount = item_base_price  # Use base price if no bids
        
        # Display the item details with circular image
        st.markdown(
            f"""
            <div style="display: flex; align-items: center; gap: 20px;">
                <div style="flex-shrink: 0;">
                    <img src="{item_image_url}" style="width: 80px; height: 80px; border-radius: 50%; object-fit: cover;"/>
                </div>
                <div>
                    <h4 style="margin: 0;">{item_name}</h4>
                    <p style="margin: 0;">Current Bidder: {current_bidder}</p>
                    <p style="margin: 0;">Current Bid Amount: {format_amount(current_bid_amount)}</p>
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )
        
        # Check if the user has selected a team and entered the password
        if 'selected_team' in st.session_state and 'team_password' in st.session_state:
            if st.button("    💰                      Bid", key="big_bid"):
                # Logic to place a big bid
                place_bid(item_id, st.session_state['selected_team'], current_bid_amount)
                st.success("Big Bid placed successfully!")
        else:
            st.warning("Please select a team and enter the password in the Bidding & Budgets tab to enable bidding.")
    else:
        st.warning("No item is currently available for bidding.")