from . import admin, history, loans, payments, stats, trash

routers = [
    stats.router,
    admin.router,
    loans.router,
    payments.router,
    trash.router,
    history.router,
]

__all__ = ["routers"]
