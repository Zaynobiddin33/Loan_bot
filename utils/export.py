from __future__ import annotations

from .formatters import format_amount, format_timestamp, now_local


def _proof_label(item: dict) -> str:
    if item["proof_type"] == "image":
        if item.get("note"):
            return f'Skrinshot ({item["note"]})'
        return "Skrinshot"
    return f'Matn: {item["proof_content"]}'


def _status_label(status: str) -> str:
    return {
        "active": "FAOL",
        "paid": "TO'LANGAN",
        "cancelled": "BEKOR QILINGAN",
    }.get(status, status.upper())


def build_history_text(
    group_name: str,
    period_label: str,
    start_text: str,
    end_text: str,
    records: dict,
) -> str:
    loans = records["loans"]
    payments = records["payments"]

    lines: list[str] = [
        f"=== QARZ TARIXI: {group_name} ===",
        f"Davr: {start_text} dan {end_text} gacha",
        f"Yaratildi: {now_local().strftime('%Y-%m-%d %H:%M')}",
        f"Tanlangan davr: {period_label}",
        "===============================",
        "",
    ]

    for index, loan in enumerate(loans, start=1):
        lines.extend(
            [
                f"[QARZ #{index}]",
                "Tur: Qarz berildi",
                f"Sana: {format_timestamp(loan['created_at'])}",
                f"Kimdan: {loan['from_name']}",
                f"Kimga: {loan['to_name']}",
                f"Summasi: {format_amount(loan['amount'])}",
                f"Izoh: {loan['comment']}",
                f"Holat: {_status_label(loan['status'])}",
                "",
            ]
        )

    for index, payment in enumerate(payments, start=1):
        lines.extend(
            [
                f"[TO'LOV #{index}]",
                "Tur: To'lov",
                f"Sana: {format_timestamp(payment['approved_at'])}",
                f"Kimdan: {payment['from_name']}",
                f"Kimga: {payment['to_name']}",
                f"Summasi: {format_amount(payment['amount'])}",
                f"Dalil: {_proof_label(payment)}",
                "",
            ]
        )

    total_loans = sum(float(item["amount"]) for item in loans)
    total_payments = sum(float(item["amount"]) for item in payments)

    lines.extend(
        [
            "================================",
            "XULOSA:",
            f"Davrdagi qarzlar jami: {format_amount(total_loans)}",
            f"Davrdagi to'lovlar jami: {format_amount(total_payments)}",
            "================================",
        ]
    )

    return "\n".join(lines)
