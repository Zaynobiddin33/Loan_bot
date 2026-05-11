from . import admin, history, loans, payments, reminders, stats, trash

routers = [
    stats.router,
    admin.router,
    loans.router,
    payments.router,
    trash.router,
    history.router,
    reminders.router,
]

__all__ = ["routers"]
