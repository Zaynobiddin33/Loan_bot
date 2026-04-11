from aiogram.fsm.state import State, StatesGroup


class AdminStates(StatesGroup):
    waiting_group_name = State()
    waiting_member_id = State()
    waiting_member_name = State()
    waiting_remove_confirm = State()
    setting_trash_order = State()


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
