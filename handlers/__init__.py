from . import admin, history, loans, payments, stats

routers = [
    stats.router,
    admin.router,
    loans.router,
    payments.router,
    history.router,
]

__all__ = ["routers"]
