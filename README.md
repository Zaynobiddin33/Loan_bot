# Loan Bot

`Loan Bot` is a Telegram bot for tracking debts inside small trusted groups. It lets an admin create groups and add members, then helps members record shared expenses, repayments, card numbers, statistics, and exportable history reports.

The bot interface is currently in Uzbek, while this README is written for developers and deployers.

## Features

- Create and manage debt groups from Telegram
- Add members by forwarding one of their messages or by entering their Telegram ID manually
- Configure the member order used for `Musor Navbat`
- Record a shared expense and split it across selected participants
- Exclude the lender's own share from debt creation when the lender also took part in the expense
- Repay debts partially or fully
- Attach repayment proof as either text or an image
- Show per-group personal statistics:
  - who owes you
  - who you owe
  - total loaned out
  - total repaid
  - net position
- Store and reveal saved card numbers from the stats screen
- Show `Musor Navbat` for each group with every-other-day trash duty rotation
- Send an automatic 08:00 reminder to the member whose trash duty is active that day
- Export group history as a `.txt` report for:
  - today
  - this week
  - this month
  - all time
- Prevent multiple bot instances from running at the same time with a PID lock

## Tech Stack

- Python
- `aiogram` 3
- SQLite
- `python-dotenv`
- `APScheduler` for daily trash-duty reminders

## How The Bot Works

### Admin flow

Admins are defined through the `ADMIN_IDS` value in `.env`. On startup, those IDs are synced into the `admins` table automatically.

Admin-only actions:

- `➕ Guruh yaratish` to create a group
- `👤 A'zo qo'shish` to add a member
- `🗑 A'zoni o'chirish` to remove a member
- `🔁 Musor tartibi` to set the trash-duty order for a group
- `📋 Guruhlar` to view owned groups, member counts, and active debt totals

When a group is created, the admin is also added as that group's first member.

### Member flow

Members can:

- `💸 Qarzni berish` to record a loan/shared expense
- `💰 Qarzni to'lash` to repay a debt
- `🗑 Musor Navbat` to see whose turn it is to take out the trash
- `📊 Statistikam` to view balances and totals
- `📋 Tarix` to export group history
- `💳 Kartam` to save or update a card number
- `👥 Guruhlarim` to see the groups they belong to

The bot uses button-based flows and FSM states for multi-step actions.

## Musor Navbat Logic

Each group has its own trash-duty rotation.

- The rotation starts from the day the feature is initialized for that group
- Active duty happens every other day
- The day between duties is a skip day with no assignee
- Group members are rotated in the admin-defined order
- At `08:00` Asia/Tashkent time, the active member for that day receives a reminder

## Loan And Payment Logic

### Loan creation

When a user records a loan:

1. They choose a group.
2. They select all participants involved in the shared expense.
3. They enter the total amount.
4. The bot splits the amount evenly across selected participants.
5. If the lender included themselves in the participant list, their own share is excluded from debt creation.
6. A separate debt record is created for each borrower.

### Repayment

When a user repays a debt:

1. They choose a group.
2. The bot shows creditors they currently owe.
3. They select a creditor and enter an amount up to the current net debt.
4. They send proof as text or a screenshot.
5. The payment is automatically allocated across outstanding loans in chronological order.

## Data Storage

The bot stores data in SQLite at:

`data/db.sqlite3`

Tables currently used:

- `admins`
- `groups`
- `group_members`
- `loans`
- `payments`
- `trash_rotation_settings`

The database schema is created automatically on startup.

## Configuration

Create a `.env` file in the project root:

```env
BOT_TOKEN=your_telegram_bot_token
ADMIN_IDS=123456789,987654321
```

### Environment variables

- `BOT_TOKEN`
  - Required
  - Telegram bot token from BotFather
- `ADMIN_IDS`
  - Optional but strongly recommended
  - Comma-separated Telegram user IDs allowed to use the admin panel

If `BOT_TOKEN` is missing, the bot will stop at startup.

## Local Setup

### 1. Create and activate a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Create `.env`

Add `BOT_TOKEN` and at least one admin ID.

### 4. Run the bot

```bash
python main.py
```

The bot uses long polling, not webhooks.

## Deployment

This repository includes:

- `run.sh`
- `loan_bot.service`

They are prepared for a Linux server deployment with:

- working directory: `/home/ubuntu/loan_bot`
- user: `ubuntu`

If your server paths differ, update both files before enabling the service.

### Example `systemd` setup

```bash
sudo cp loan_bot.service /etc/systemd/system/loan_bot.service
sudo systemctl daemon-reload
sudo systemctl enable loan_bot
sudo systemctl start loan_bot
sudo systemctl status loan_bot
```

## Project Structure

```text
loan_bot/
├── main.py                # Bot startup, polling, single-instance lock
├── config.py              # Environment loading and path config
├── states.py              # FSM states
├── requirements.txt
├── run.sh
├── loan_bot.service
├── data/
│   └── db.sqlite3         # SQLite database
├── db/
│   ├── models.py          # Schema creation
│   └── queries.py         # Database operations and debt logic
├── handlers/
│   ├── admin.py           # Group and member management
│   ├── history.py         # History export
│   ├── loans.py           # Loan creation flow
│   ├── payments.py        # Repayment flow
│   ├── stats.py           # Main menu, stats, card storage
│   └── trash.py           # Trash-duty lookup and reminders
├── keyboards/
│   └── menus.py           # Reply and inline keyboards
├── middlewares/
│   └── group_check.py     # Access checks for group-based actions
└── utils/
    ├── export.py          # History export text builder
    └── formatters.py      # Amount/date helpers
```

## Notes

- Group-restricted actions are blocked for users who are not part of any group.
- Notifications to members and creditors are best-effort; Telegram may reject them if the user has not started the bot or has blocked it.
- A PID lock file named `.bot.pid` is created while the bot is running to prevent duplicate instances.
- The repo currently contains a local `venv/` directory, but it is normally best to create your own environment per machine.

## Current Gaps

- There are no automated tests in the repository yet.
- There is no `.env.example` template yet.
- The included `systemd` files use hard-coded server paths and should be adjusted for your environment.

## License

No license file is currently included in this repository.
