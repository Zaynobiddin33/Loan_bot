You are building a production-ready Telegram accounting bot using Python, Aiogram 3.x, and SQLite (using aiosqlite) in /home/ubuntu/loan_bot/. This is NOT a payment processor — it is a group-based loan accounting and tracking system for small trusted groups (friends, colleagues, roommates, etc.).

---

## TECH STACK

- Python 3.11+
- Aiogram 3.x (async Telegram bot framework)
- SQLite via aiosqlite (single file DB: data/db.sqlite3)
- No external payment APIs needed
- python-dotenv for config
- Pillow or aiofiles for handling media uploads
- APScheduler (optional) for any scheduled jobs
- Structure the project cleanly:

loan_bot/
├── main.py
├── .env
├── requirements.txt
├── data/
│   └── db.sqlite3
├── handlers/
│   ├── __init__.py
│   ├── admin.py
│   ├── loans.py
│   ├── payments.py
│   ├── stats.py
│   └── history.py
├── db/
│   ├── __init__.py
│   ├── models.py        # CREATE TABLE statements + init
│   └── queries.py       # All DB query functions
├── keyboards/
│   ├── __init__.py
│   └── menus.py         # All InlineKeyboardMarkup and ReplyKeyboardMarkup builders
├── utils/
│   ├── __init__.py
│   ├── formatters.py    # Text formatting helpers
│   └── export.py        # .txt history file generator
└── middlewares/
    └── group_check.py   # Middleware to verify user is in a group

---

## DATABASE SCHEMA

Create these tables:

admins(id INTEGER PRIMARY KEY, telegram_id BIGINT UNIQUE NOT NULL)

groups(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  admin_id BIGINT NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)

group_members(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  group_id INTEGER REFERENCES groups(id),
  telegram_id BIGINT NOT NULL,
  username TEXT,
  full_name TEXT,
  card_number TEXT,
  joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(group_id, telegram_id)
)

loans(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  group_id INTEGER REFERENCES groups(id),
  lender_id BIGINT NOT NULL,        -- person who gave money
  borrower_id BIGINT NOT NULL,      -- person who owes money
  amount REAL NOT NULL,
  comment TEXT,
  status TEXT DEFAULT 'active',     -- 'active' | 'paid' | 'cancelled'
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)

payments(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  loan_id INTEGER REFERENCES loans(id),
  payer_id BIGINT NOT NULL,
  amount REAL NOT NULL,
  proof_type TEXT,                  -- 'image' | 'text'
  proof_content TEXT,               -- file_id or text message
  note TEXT,
  approved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)

---

## CORE BUSINESS LOGIC

### Net Balance / Cancellation Logic
When Person A owes Person B $50 and Person B owes Person A $30, they should be netted:
- Net result: Person A owes Person B $20
- Implement a function `get_net_balance(group_id, person_a_id, person_b_id)` that returns the net amount and direction
- Display netted balances everywhere in the UI, not raw loan records

### Equal Split Logic
When a lender selects multiple borrowers (or "All"), divide the total amount equally:
- Example: $100 split among 5 people → each owes $20
- Create individual loan records for each borrower (one row per pair), NOT a single group record
- Round to 2 decimal places; if rounding causes remainder, add it to the first borrower

---

## BOT FLOWS — IMPLEMENT ALL OF THESE

### /start Command
- If user is NOT registered in any group: show a friendly welcome message explaining what the bot does
- If user IS a member of one or more groups (added by admin): automatically show their group(s) and enter the main menu
- If user is an admin: show admin panel + regular user menu

### MAIN MENU (Reply Keyboard for registered users)
Buttons:
[ 💸 Give Loan ]   [ 💰 Pay Debt ]
[ 📊 My Stats  ]   [ 📋 History  ]
[ 💳 My Card   ]   [ 👥 My Groups]

### ADMIN PANEL (shown to admins only, above main menu)
Buttons:
[ ➕ Create Group ]  [ 👤 Add Member ]
[ 🗑 Remove Member ] [ 📋 Manage Groups ]

---

## FEATURE SPECS

### 1. ADMIN — Create Group
- Admin sends /start or taps "Create Group"
- Bot asks: "Enter a name for your new group:"
- After name is entered, group is created with admin as owner
- Confirmation: "✅ Group '[name]' created! Now add members using 'Add Member'."

### 2. ADMIN — Add Member
- Show list of admin's groups (inline keyboard)
- Admin selects a group
- Bot asks: "Forward a message from the user you want to add, OR send their Telegram user ID:"
- On forward: extract user info and add to group
- On ID: add by numeric Telegram ID
- If user has already used /start, they immediately see the group on next interaction
- Confirmation sent to both admin and the added member: "🎉 You've been added to group '[name]' by [admin]!"

### 3. ADMIN — Remove Member
- Select group → select member → confirm → remove
- Notify removed member: "You have been removed from group '[name]'."

### 4. GIVE LOAN
Step-by-step FSM (Finite State Machine) flow:

Step 1 — Select Group (if user is in multiple groups, show choice; else auto-select)
Step 2 — Select Borrower(s):
  - Show all group members except self as inline checkboxes (multi-select)
  - Add a "✅ All Members" toggle button at the top
  - Show "➡️ Continue" button once at least one is selected
Step 3 — Enter Amount:
  - "Enter the total loan amount (e.g. 150000):"
  - Validate: must be positive number
  - If multiple borrowers selected: show split preview "Each person will owe: X (total Y ÷ Z people)"
Step 4 — Enter Comment:
  - "Add a comment for this loan (e.g. 'Dinner at restaurant', 'Taxi fare'):"
  - This is REQUIRED, not optional
Step 5 — Confirm:
  - Show summary card:
    "💸 Loan Summary
     From: You
     To: [names]
     Amount: [X] each (Total: [Y])
     Comment: [comment]
     [✅ Confirm] [❌ Cancel]"
Step 6 — On confirm:
  - Create loan records
  - Send notification to each borrower:
    "⚠️ New loan recorded!
     From: [lender name]
     Amount: [X]
     Comment: [comment]
     Use 'Pay Debt' to settle this."

### 5. PAY DEBT
Step-by-step FSM flow:

Step 1 — Select Group
Step 2 — Select Creditor (person you owe money to):
  - Show only people you currently owe (with net amounts)
  - Each button shows: "[Name] — owes [amount]"
Step 3 — Enter Amount to Pay:
  - Show current net debt to this person
  - "How much are you paying? (max: [net_amount]):"
  - Validate: must be ≤ net debt
Step 4 — Upload Proof:
  - "Send proof of payment — a screenshot or a text note:"
  - Accept BOTH photo (file_id stored) AND text message as proof
Step 5 — Confirm:
  - Show summary and confirm button
Step 6 — On confirm:
  - Mark relevant loan(s) as paid (partial or full)
  - Send notification to creditor:
    "💰 Payment received!
     From: [name]
     Amount: [X]
     Proof: [attached image or text]
     ✅ This has been automatically recorded."

### 6. MY STATS
Show a detailed personal stats card for the selected group:

"📊 Your Stats in [Group Name]

💸 Total you have loaned out: [X]
💰 Total you owe others: [Y]
📈 Net position: [+Z you are owed / -Z you owe]

--- Breakdown ---

You owe:
  • [Name 1]: [amount]
  • [Name 2]: [amount]

People owe you:
  • [Name 3]: [amount]
  • [Name 4]: [amount]

--- All Time ---
Total loans you gave (all time): [X]
Total loans paid to you: [X]
Total loans you paid: [X]"

- Use net balances (cancellation applied)
- Show 💳 card numbers with a tap: "Tap a name to see their card number"

### 7. MY CARD
- Show current saved card: "💳 Your card: [number] — tap to update"
- Or if none: "You haven't added a card yet."
- "Enter your card number:" → validate → save
- Card number is visible to group members when they tap your name in stats or pay debt

### 8. HISTORY (export)
Step 1 — Select Group
Step 2 — Select Period:
  [ 📅 Today ] [ 📅 This Week ] [ 📅 This Month ] [ 📅 All Time ]
Step 3 — Generate and send a .txt file with ALL transactions in that period:

Format of history.txt:
=== LOAN HISTORY: [Group Name] ===
Period: [start] to [end]
Generated: [timestamp]
===============================

[LOAN #1]
Type: Loan Given
Date: 2024-01-15 14:32
From: Alice
To: Bob
Amount: 5000
Comment: Lunch money
Status: ACTIVE

[PAYMENT #1]
Type: Payment
Date: 2024-01-16 09:10
From: Bob
To: Alice
Amount: 5000
Proof: [Screenshot / "Text: paid via cash"]
================================
SUMMARY:
Total loans in period: [X]
Total payments in period: [X]
================================

- Send as a document (bot.send_document) not as message text
- File named: history_[groupname]_[period].txt

---

## UI/UX REQUIREMENTS

1. Use InlineKeyboardMarkup for multi-step flows (FSM), ReplyKeyboardMarkup for main persistent menu
2. Every action must have a ❌ Cancel button that returns to main menu
3. Paginate member lists if > 8 members (prev/next buttons)
4. All monetary amounts formatted with thousands separator (e.g. 1,500,000 not 1500000)
5. All timestamps in Uzbekistan timezone (UTC+5, Asia/Tashkent) — use pytz
6. Emoji-rich messages but not overwhelming — use sparingly for key info
7. Error messages must be friendly: "⚠️ That doesn't look like a valid amount. Please enter a number like 5000 or 12500."
8. After every successful action, return to main menu automatically after 2 seconds OR show a "🏠 Back to Menu" button
9. Loading indicators: for DB operations use "⏳ Processing..." edit before final message

---

## FSM STATES

Use Aiogram's FSM with MemoryStorage. Define these state groups:

class AdminStates(StatesGroup):
    waiting_group_name = State()
    waiting_member_id = State()
    waiting_remove_confirm = State()

class LoanStates(StatesGroup):
    select_group = State()
    select_borrowers = State()
    enter_amount = State()
    enter_comment = State()
    confirm_loan = State()

class PaymentStates(StatesGroup):
    select_group = State()
    select_creditor = State()
    enter_amount = State()
    upload_proof = State()
    confirm_payment = State()

class CardStates(StatesGroup):
    enter_card = State()

---

## ERROR HANDLING & EDGE CASES

1. User not in any group → show onboarding message, cannot use features
2. Group has only 1 member → "Add more members before giving loans"
3. User tries to give loan to themselves → prevent it silently
4. Paying more than owed → block with error
5. Double tap on confirm button → use callback answer + edit to prevent duplicate records
6. Deleted Telegram accounts in group → handle gracefully, show as "Unknown User (#id)"
7. Bot blocked by user → catch TelegramForbiddenError when sending notifications
8. Invalid card number format → warn but allow saving (don't over-validate, different countries)
9. DB errors → log to console + send "Something went wrong, try again" to user

---

## SETUP & RUN

Create a .env file template:
BOT_TOKEN=your_token_here
ADMIN_IDS=123456789,987654321   # comma-separated list of admin Telegram IDs

Create requirements.txt with pinned versions.
Create a run.sh:
  cd /home/ubuntu/loan_bot && source venv/bin/activate && python main.py

Create a systemd service file loan_bot.service for auto-start on server reboot.

In main.py:
- Initialize DB on startup (create tables if not exist)
- Register all routers
- Use asyncio.run(main())
- Log startup with bot username confirmation

---

## FINAL NOTES

- Write complete, working code — no placeholders, no "TODO" comments
- Each handler file should be self-contained with its router
- All DB operations must be async (aiosqlite)
- Test every FSM flow mentally before writing — no dead ends
- The bot must work end-to-end for a group of 5–20 people with dozens of loans
- Comment the code clearly in English
- After writing all files, print a summary of what was created and how to run it