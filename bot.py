"""
Slotex User Bot — Phase 1
All logic in one file: handlers, DB, keyboards, helpers.
"""
import os
import random
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv

import turso_serverless
from aiogram import Bot, Dispatcher, types, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
    ReplyKeyboardRemove
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
TURSO_URL = os.getenv("TURSO_DATABASE_URL")
TURSO_TOKEN = os.getenv("TURSO_AUTH_TOKEN")
PROOF_CHANNEL_ID = os.getenv("PROOF_CHANNEL_ID")

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("slotex")

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher(storage=MemoryStorage())

# ─────────────────────────────────────────────
# DATABASE HELPERS
# ─────────────────────────────────────────────
def db():
    return turso_serverless.connect(TURSO_URL, auth_token=TURSO_TOKEN)

def q_exec(sql, params=()):
    c = db()
    try:
        cur = c.execute(sql, params)
        c.commit()
        return cur.lastrowid
    finally:
        c.close()

def q_one(sql, params=()):
    c = db()
    try:
        return c.execute(sql, params).fetchone()
    finally:
        c.close()

def q_all(sql, params=()):
    c = db()
    try:
        return c.execute(sql, params).fetchall()
    finally:
        c.close()

def get_setting(key, default=None):
    row = q_one("SELECT value FROM settings WHERE key=?", (key,))
    return row[0] if row else default

def gen_account_no():
    while True:
        n = str(random.randint(100000, 999999))
        if not q_one("SELECT 1 FROM users WHERE account_no=?", (n,)):
            return n

# ─────────────────────────────────────────────
# STATES
# ─────────────────────────────────────────────
class Reg(StatesGroup):
    name = State()
    mobile = State()
    password = State()
    referral = State()

class Log(StatesGroup):
    mobile = State()
    password = State()

class Forgot(StatesGroup):
    mobile = State()
    otp = State()
    newpass = State()

# ─────────────────────────────────────────────
# KEYBOARDS
# ─────────────────────────────────────────────
def kb_welcome():
    b = InlineKeyboardBuilder()
    b.button(text="🔐 Login", callback_data="auth_login")
    b.button(text="🆕 New Registration", callback_data="auth_reg")
    b.button(text="🔑 Forgot Password", callback_data="auth_forgot")
    b.adjust(1)
    return b.as_markup()

def kb_main():
    b = ReplyKeyboardBuilder()
    b.button(text="👤 Profile")
    b.button(text="💸 Withdraw")
    b.button(text="🎮 Order")
    b.button(text="👥 Referral")
    b.button(text="📜 History")
    b.adjust(2, 2, 1)
    return b.as_markup(resize_keyboard=True)

def kb_cancel():
    b = InlineKeyboardBuilder()
    b.button(text="❌ Cancel", callback_data="cancel_flow")
    return b.as_markup()

# ─────────────────────────────────────────────
# /start + CANCEL
# ─────────────────────────────────────────────
@dp.message(CommandStart())
async def cmd_start(msg: types.Message, state: FSMContext):
    await state.clear()
    await msg.answer(
        "👋 <b>Welcome to Slotex</b>\n\n"
        "India's trusted gaming order platform.\n"
        "Please choose an option below:",
        reply_markup=kb_welcome()
    )

@dp.callback_query(F.data == "cancel_flow")
async def cancel_flow(cb: types.CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await cb.message.edit_text("❌ Cancelled. Use /start to begin again.")
    except Exception:
        await cb.message.answer("❌ Cancelled. Use /start to begin again.")
    await cb.answer()

# ─────────────────────────────────────────────
# REGISTRATION
# ─────────────────────────────────────────────
@dp.callback_query(F.data == "auth_reg")
async def reg_start(cb: types.CallbackQuery, state: FSMContext):
    await state.set_state(Reg.name)
    try:
        await cb.message.edit_text(
            "📝 <b>Registration</b>\n\nEnter your <b>full name</b>:",
            reply_markup=kb_cancel()
        )
    except Exception:
        await cb.message.answer(
            "📝 <b>Registration</b>\n\nEnter your <b>full name</b>:",
            reply_markup=kb_cancel()
        )
    await cb.answer()

@dp.message(Reg.name)
async def reg_name(msg: types.Message, state: FSMContext):
    if not msg.text or len(msg.text.strip()) < 2:
        return await msg.answer("Name too short. Try again:")
    await state.update_data(name=msg.text.strip())
    await state.set_state(Reg.mobile)
    await msg.answer("📱 Enter your <b>10-digit mobile number</b>:")

@dp.message(Reg.mobile)
async def reg_mobile(msg: types.Message, state: FSMContext):
    m = (msg.text or "").strip()
    if not (m.isdigit() and len(m) == 10):
        return await msg.answer("❌ Invalid. Send exactly 10 digits.")
    await state.update_data(mobile=m)
    await state.set_state(Reg.password)
    await msg.answer("🔒 Set a <b>password</b> (min 4 characters):")

@dp.message(Reg.password)
async def reg_password(msg: types.Message, state: FSMContext):
    p = (msg.text or "").strip()
    if len(p) < 4:
        return await msg.answer("Password too short. Min 4 chars:")
    await state.update_data(password=p)
    await state.set_state(Reg.referral)
    await msg.answer(
        "🎁 Enter <b>referral account number</b> (6 digits)\n"
        "or send <code>skip</code> to continue:"
    )

@dp.message(Reg.referral)
async def reg_referral(msg: types.Message, state: FSMContext):
    ref = (msg.text or "").strip().lower()
    ref_acc = None
    if ref != "skip":
        if not (ref.isdigit() and len(ref) == 6):
            return await msg.answer("Invalid. Send 6-digit account no or 'skip':")
        if not q_one("SELECT 1 FROM users WHERE account_no=?", (ref,)):
            return await msg.answer("❌ Referral account not found. Try again or 'skip':")
        ref_acc = ref

    data = await state.get_data()
    acc = gen_account_no()
    tg_id = str(msg.from_user.id)

    q_exec(
        "INSERT INTO users(tg_id,name,mobile,password,account_no,referral_by) "
        "VALUES(?,?,?,?,?,?)",
        (tg_id, data["name"], data["mobile"], data["password"], acc, ref_acc)
    )
    await state.clear()
    await msg.answer(
        f"✅ <b>Registration Successful!</b>\n\n"
        f"👤 Name: {data['name']}\n"
        f"📱 Mobile: {data['mobile']}\n"
        f"🆔 Account No: <code>{acc}</code>\n\n"
        f"Use /start → Login to continue.",
        reply_markup=ReplyKeyboardRemove()
    )

# ─────────────────────────────────────────────
# LOGIN
# ─────────────────────────────────────────────
@dp.callback_query(F.data == "auth_login")
async def login_start(cb: types.CallbackQuery, state: FSMContext):
    await state.set_state(Log.mobile)
    try:
        await cb.message.edit_text(
            "🔐 <b>Login</b>\n\nEnter your <b>mobile number</b>:",
            reply_markup=kb_cancel()
        )
    except Exception:
        await cb.message.answer(
            "🔐 <b>Login</b>\n\nEnter your <b>mobile number</b>:",
            reply_markup=kb_cancel()
        )
    await cb.answer()

@dp.message(Log.mobile)
async def login_mobile(msg: types.Message, state: FSMContext):
    m = (msg.text or "").strip()
    if not (m.isdigit() and len(m) == 10):
        return await msg.answer("❌ Invalid. Send 10 digits.")
    await state.update_data(mobile=m)
    await state.set_state(Log.password)
    await msg.answer("🔒 Enter your <b>password</b>:")

@dp.message(Log.password)
async def login_password(msg: types.Message, state: FSMContext):
    data = await state.get_data()
    tg_id = str(msg.from_user.id)
    row = q_one(
        "SELECT id,name,account_no,balance,is_banned FROM users "
        "WHERE mobile=? AND password=? AND tg_id=?",
        (data["mobile"], (msg.text or "").strip(), tg_id)
    )
    if not row:
        await state.clear()
        return await msg.answer("❌ Invalid credentials for this Telegram account.")
    if row[4]:
        await state.clear()
        return await msg.answer("🚫 Your account is banned. Contact support.")

    await state.clear()
    await state.update_data(user_id=row[0], name=row[1], account_no=row[2])
    await msg.answer(
        f"✅ <b>Welcome back, {row[1]}!</b>\n\n"
        f"🆔 Account: <code>{row[2]}</code>\n"
        f"💰 Balance: ₹{row[3]:.2f}",
        reply_markup=kb_main()
    )

# ─────────────────────────────────────────────
# FORGOT PASSWORD
# ─────────────────────────────────────────────
@dp.callback_query(F.data == "auth_forgot")
async def forgot_start(cb: types.CallbackQuery, state: FSMContext):
    await state.set_state(Forgot.mobile)
    try:
        await cb.message.edit_text(
            "🔑 <b>Forgot Password</b>\n\nEnter your registered <b>mobile number</b>:",
            reply_markup=kb_cancel()
        )
    except Exception:
        await cb.message.answer(
            "🔑 <b>Forgot Password</b>\n\nEnter your registered <b>mobile number</b>:",
            reply_markup=kb_cancel()
        )
    await cb.answer()

@dp.message(Forgot.mobile)
async def forgot_mobile(msg: types.Message, state: FSMContext):
    m = (msg.text or "").strip()
    tg_id = str(msg.from_user.id)
    row = q_one(
        "SELECT name FROM users WHERE mobile=? AND tg_id=?",
        (m, tg_id)
    )
    if not row:
        return await msg.answer("❌ No account with this number under your Telegram ID.")
    otp = str(random.randint(100000, 999999))
    expires = (datetime.utcnow() + timedelta(minutes=5)).isoformat()
    q_exec(
        "INSERT OR REPLACE INTO otp_codes(mobile,otp,expires_at) VALUES(?,?,?)",
        (m, otp, expires)
    )
    masked = m[:2] + "****" + m[-4:]
    await state.update_data(mobile=m)
    await state.set_state(Forgot.otp)
    await msg.answer(
        f"📩 <b>OTP Sent</b>\n\n"
        f"👤 Name: {row[0]}\n"
        f"📱 Mobile: {masked}\n"
        f"🔢 OTP: <code>{otp}</code>\n\n"
        f"⏱ Valid for 5 minutes. Enter OTP:"
    )

@dp.message(Forgot.otp)
async def forgot_otp(msg: types.Message, state: FSMContext):
    data = await state.get_data()
    row = q_one(
        "SELECT otp,expires_at FROM otp_codes WHERE mobile=?",
        (data["mobile"],)
    )
    if not row:
        return await msg.answer("❌ No OTP found. Start again with /start.")
    try:
        exp = datetime.fromisoformat(row[1])
    except Exception:
        return await msg.answer("❌ OTP invalid. Start again with /start.")
    if datetime.utcnow() > exp:
        return await msg.answer("⏱ OTP expired. Start again with /start.")
    if (msg.text or "").strip() != row[0]:
        return await msg.answer("❌ Wrong OTP. Try again:")
    await state.set_state(Forgot.newpass)
    await msg.answer("✅ OTP verified. Enter your <b>new password</b>:")

@dp.message(Forgot.newpass)
async def forgot_newpass(msg: types.Message, state: FSMContext):
    p = (msg.text or "").strip()
    if len(p) < 4:
        return await msg.answer("Too short. Min 4 chars:")
    data = await state.get_data()
    q_exec("UPDATE users SET password=? WHERE mobile=?", (p, data["mobile"]))
    q_exec("DELETE FROM otp_codes WHERE mobile=?", (data["mobile"],))
    await state.clear()
    await msg.answer("✅ Password updated! Use /start → Login.")

# ─────────────────────────────────────────────
# MAIN MENU HANDLERS
# ─────────────────────────────────────────────
@dp.message(F.text == "👤 Profile")
async def menu_profile(msg: types.Message, state: FSMContext):
    data = await state.get_data()
    uid = data.get("user_id")
    if not uid:
        return await msg.answer("Please login first via /start")
    row = q_one(
        "SELECT name,mobile,account_no,tg_id,balance FROM users WHERE id=?",
        (uid,)
    )
    if not row:
        return await msg.answer("Session expired. /start again.")
    await msg.answer(
        f"👤 <b>Your Profile</b>\n\n"
        f"Name: {row[0]}\n"
        f"Mobile: {row[1]}\n"
        f"Account No: <code>{row[2]}</code>\n"
        f"Telegram ID: <code>{row[3]}</code>\n"
        f"💰 Balance: ₹{row[4]:.2f}"
    )

@dp.message(F.text.in_({"👥 Referral", "📜 History"}))
async def menu_soon(msg: types.Message):
    await msg.answer("🚧 This feature arrives in the next phase.")

# ─────────────────────────────────────────────
# RUN
# ─────────────────────────────────────────────
# MAIN_REMOVED


class Withdraw(StatesGroup):
    wallet = State()
    coin = State()
    network = State()
    upi_id = State()
    upi_bank = State()
    bank_acc = State()
    banking_name = State()
    bank_ifsc = State()
    amount = State()


def kb_withdraw_methods():
    b = InlineKeyboardBuilder()
    b.button(text="Crypto", callback_data="wd_crypto")
    b.button(text="UPI", callback_data="wd_upi")
    b.button(text="Bank", callback_data="wd_bank")
    b.button(text="Cancel", callback_data="cancel_flow")
    b.adjust(3, 1)
    return b.as_markup()


@dp.message(F.text == "💸 Withdraw")
async def menu_withdraw(msg: types.Message, state: FSMContext):
    print("[WD] Handler called!")
    data = await state.get_data()
    uid = data.get("user_id")
    if not uid:
        return await msg.answer("Please login first via /start")

    pending = q_one(
        "SELECT id FROM withdrawals WHERE user_id=? AND status='pending'",
        (uid,)
    )
    if pending:
        return await msg.answer(
            "Aapka pehle se ek withdrawal request pending hai."
        )

    row = q_one("SELECT balance FROM users WHERE id=?", (uid,))
    balance = row[0] if row else 0

    await state.set_state(None)
    await msg.answer(
        f"Withdrawal\n\n"
        f"Balance: Rs {balance:.2f}\n"
        f"Min Withdrawal: Rs {get_setting('min_withdrawal', '100')}\n\n"
        f"Choose your withdrawal method:",
        reply_markup=kb_withdraw_methods()
    )


@dp.callback_query(F.data == "wd_crypto")
async def wd_crypto_start(cb: types.CallbackQuery, state: FSMContext):
    await state.set_state(Withdraw.wallet)
    await state.update_data(method="Crypto")
    try:
        await cb.message.edit_text(
            "Crypto Withdrawal\n\nEnter your Wallet Address:",
            reply_markup=kb_cancel()
        )
    except Exception:
        await cb.message.answer(
            "Crypto Withdrawal\n\nEnter your Wallet Address:",
            reply_markup=kb_cancel()
        )
    await cb.answer()


@dp.message(Withdraw.wallet)
async def wd_wallet(msg: types.Message, state: FSMContext):
    w = (msg.text or "").strip()
    if len(w) < 10:
        return await msg.answer("Wallet address too short. Try again:")
    await state.update_data(wallet=w)
    await state.set_state(Withdraw.coin)
    await msg.answer("Enter coin type (e.g. USDT, BTC, ETH):")


@dp.message(Withdraw.coin)
async def wd_coin(msg: types.Message, state: FSMContext):
    c = (msg.text or "").strip().upper()
    if len(c) < 2:
        return await msg.answer("Invalid coin. Try again:")
    await state.update_data(coin=c)
    await state.set_state(Withdraw.network)
    await msg.answer("Enter network (e.g. TRC20, ERC20, BEP20):")


@dp.message(Withdraw.network)
async def wd_network(msg: types.Message, state: FSMContext):
    n = (msg.text or "").strip().upper()
    if len(n) < 3:
        return await msg.answer("Invalid network. Try again:")
    await state.update_data(network=n)
    await state.set_state(Withdraw.amount)
    await show_amount_prompt(msg, state)


@dp.callback_query(F.data == "wd_upi")
async def wd_upi_start(cb: types.CallbackQuery, state: FSMContext):
    await state.set_state(Withdraw.upi_id)
    await state.update_data(method="UPI")
    try:
        await cb.message.edit_text(
            "UPI Withdrawal\n\nEnter your UPI ID (e.g. name@upi):",
            reply_markup=kb_cancel()
        )
    except Exception:
        await cb.message.answer(
            "UPI Withdrawal\n\nEnter your UPI ID (e.g. name@upi):",
            reply_markup=kb_cancel()
        )
    await cb.answer()


@dp.message(Withdraw.upi_id)
async def wd_upi_id(msg: types.Message, state: FSMContext):
    u = (msg.text or "").strip()
    if "@" not in u or len(u) < 5:
        return await msg.answer("Invalid UPI ID. Try again:")
    await state.update_data(upi_id=u)
    await state.set_state(Withdraw.upi_bank)
    await msg.answer("Enter Banking Name:")


@dp.message(Withdraw.upi_bank)
async def wd_upi_bank(msg: types.Message, state: FSMContext):
    b = (msg.text or "").strip()
    if len(b) < 3:
        return await msg.answer("Bank name too short. Try again:")
    await state.update_data(upi_bank=b)
    await state.set_state(Withdraw.amount)
    await show_amount_prompt(msg, state)


@dp.callback_query(F.data == "wd_bank")
async def wd_bank_start(cb: types.CallbackQuery, state: FSMContext):
    await state.set_state(Withdraw.bank_acc)
    await state.update_data(method="Bank")
    try:
        await cb.message.edit_text(
            "Bank Withdrawal\n\nEnter your Account Number:",
            reply_markup=kb_cancel()
        )
    except Exception:
        await cb.message.answer(
            "Bank Withdrawal\n\nEnter your Account Number:",
            reply_markup=kb_cancel()
        )
    await cb.answer()


@dp.message(Withdraw.bank_acc)
async def wd_bank_acc(msg: types.Message, state: FSMContext):
    a = (msg.text or "").strip()
    if not a.isdigit() or len(a) < 8:
        return await msg.answer("Invalid account number (8+ digits). Try again:")
    await state.update_data(bank_acc=a)
    await state.set_state(Withdraw.banking_name)
    await msg.answer("Enter Banking Name:")


@dp.message(Withdraw.banking_name)
async def wd_banking_name(msg: types.Message, state: FSMContext):
    b = (msg.text or "").strip()
    if len(b) < 3:
        return await msg.answer("Bank name too short. Try again:")
    await state.update_data(banking_name=b)
    await state.set_state(Withdraw.bank_ifsc)
    await msg.answer("Enter your IFSC Code (e.g. SBIN0001234):")


@dp.message(Withdraw.bank_ifsc)
async def wd_bank_ifsc(msg: types.Message, state: FSMContext):
    i = (msg.text or "").strip().upper()
    if len(i) != 11 or not i[:4].isalpha() or not i[4:].isalnum():
        return await msg.answer("Invalid IFSC. Try again:")
    await state.update_data(bank_ifsc=i)
    await state.set_state(Withdraw.amount)
    await show_amount_prompt(msg, state)


async def show_amount_prompt(msg: types.Message, state: FSMContext):
    data = await state.get_data()
    uid = data.get("user_id")
    method = data.get("method", "UPI")

    row = q_one("SELECT balance FROM users WHERE id=?", (uid,))
    balance = row[0] if row else 0

    fee = float(get_setting(f"fee_{method.lower()}", "5"))
    min_wd = float(get_setting("min_withdrawal", "100"))

    await msg.answer(
        f"Enter Withdrawal Amount\n\n"
        f"Method: {method}\n"
        f"Fee: Rs {fee:.2f}\n"
        f"Min: Rs {min_wd:.2f}\n"
        f"Your Balance: Rs {balance:.2f}\n\n"
        f"Send the amount (numbers only):"
    )


@dp.message(Withdraw.amount)
async def wd_amount(msg: types.Message, state: FSMContext):
    try:
        amount = float((msg.text or "").strip())
    except ValueError:
        return await msg.answer("Invalid amount. Send a number:")

    if amount <= 0:
        return await msg.answer("Amount must be positive:")

    data = await state.get_data()
    uid = data.get("user_id")
    method = data.get("method", "UPI")

    fee = float(get_setting(f"fee_{method.lower()}", "5"))
    min_wd = float(get_setting("min_withdrawal", "100"))

    row = q_one("SELECT balance FROM users WHERE id=?", (uid,))
    balance = row[0] if row else 0

    if amount < min_wd:
        return await msg.answer(f"Minimum withdrawal is Rs {min_wd:.2f}. Try again:")

    total = amount + fee
    if total > balance:
        return await msg.answer(
            f"Insufficient balance. Need Rs {total:.2f}, you have Rs {balance:.2f}"
        )

    pending = q_one(
        "SELECT id FROM withdrawals WHERE user_id=? AND status='pending'",
        (uid,)
    )
    if pending:
        await state.clear()
        return await msg.answer("Aapka pehle se ek withdrawal pending hai.")

    if method == "Crypto":
        details = f"Wallet: {data.get('wallet')}\nCoin: {data.get('coin')}\nNetwork: {data.get('network')}"
    elif method == "UPI":
        details = f"UPI ID: {data.get('upi_id')}\nBank: {data.get('upi_bank')}"
    else:
        details = f"Account: {data.get('bank_acc')}\nBank: {data.get('banking_name')}\nIFSC: {data.get('bank_ifsc')}"

    new_balance = balance - total
    q_exec("UPDATE users SET balance=? WHERE id=?", (new_balance, uid))

    q_exec(
        "INSERT INTO withdrawals(user_id, method, amount, fee, details, status) "
        "VALUES(?,?,?,?,?,'pending')",
        (uid, method, amount, fee, details)
    )

    await state.clear()
    await msg.answer(
        f"Withdrawal Request Submitted!\n\n"
        f"Method: {method}\n"
        f"Amount: Rs {amount:.2f}\n"
        f"Fee: Rs {fee:.2f}\n"
        f"Total Deducted: Rs {total:.2f}\n\n"
        f"Details:\n{details}\n\n"
        f"Status: Pending\n"
        f"New Balance: Rs {new_balance:.2f}"
    )


class Order(StatesGroup):
    category = State()
    url = State()
    game_uid = State()
    deposit = State()
    withdrawal = State()
    proof_deposit = State()
    proof_withdrawal = State()
    proof_stat = State()


def kb_order_category():
    b = InlineKeyboardBuilder()
    b.button(text="Crossing", callback_data="ord_crossing")
    b.button(text="Slotting", callback_data="ord_slotting")
    b.button(text="Cancel", callback_data="cancel_flow")
    b.adjust(2, 1)
    return b.as_markup()


@dp.message(F.text == "🎮 Order")
async def menu_order(msg: types.Message, state: FSMContext):
    data = await state.get_data()
    uid = data.get("user_id")
    if not uid:
        return await msg.answer("Please login first via /start")

    row = q_one(
        "SELECT name, membership_expiry FROM users WHERE id=?",
        (uid,)
    )
    if not row:
        return await msg.answer("User not found. /start again.")

    name, expiry_str = row
    active = False
    if expiry_str:
        try:
            from datetime import datetime as _dt
            if _dt.fromisoformat(expiry_str) > _dt.utcnow():
                active = True
        except Exception:
            pass

    if not active:
        return await msg.answer(
            "Membership Required\n\n"
            "Aapke paas active membership nahi hai.\n\n"
            "Available Plans:\n"
            "  - Test Plan (Free, 30 days)\n\n"
            "Membership lene ke liye /start → Profile check karo.\n"
            "(Membership flow next phase me aayega)"
        )

    await state.set_state(Order.category)
    await state.update_data(user_name=name)
    await msg.answer(
        "New Order\n\n"
        "Choose category:",
        reply_markup=kb_order_category()
    )


@dp.callback_query(F.data == "ord_crossing")
async def ord_crossing(cb: types.CallbackQuery, state: FSMContext):
    await state.update_data(category="Crossing")
    await state.set_state(Order.url)
    try:
        await cb.message.edit_text(
            "Order: Crossing\n\n"
            "Enter Working URL:",
            reply_markup=kb_cancel()
        )
    except Exception:
        await cb.message.answer(
            "Order: Crossing\n\n"
            "Enter Working URL:",
            reply_markup=kb_cancel()
        )
    await cb.answer()


@dp.callback_query(F.data == "ord_slotting")
async def ord_slotting(cb: types.CallbackQuery, state: FSMContext):
    await state.update_data(category="Slotting")
    await state.set_state(Order.url)
    try:
        await cb.message.edit_text(
            "Order: Slotting\n\n"
            "Enter Working URL:",
            reply_markup=kb_cancel()
        )
    except Exception:
        await cb.message.answer(
            "Order: Slotting\n\n"
            "Enter Working URL:",
            reply_markup=kb_cancel()
        )
    await cb.answer()


@dp.message(Order.url)
async def ord_url(msg: types.Message, state: FSMContext):
    u = (msg.text or "").strip()
    if len(u) < 5:
        return await msg.answer("URL too short. Try again:")
    await state.update_data(url=u)
    await state.set_state(Order.game_uid)
    await msg.answer("Enter Game UID:")


@dp.message(Order.game_uid)
async def ord_uid(msg: types.Message, state: FSMContext):
    uid = (msg.text or "").strip()
    if len(uid) < 3:
        return await msg.answer("UID too short. Try again:")
    await state.update_data(game_uid=uid)
    await state.set_state(Order.deposit)
    await msg.answer("Enter Deposit Amount (numbers only):")


@dp.message(Order.deposit)
async def ord_deposit(msg: types.Message, state: FSMContext):
    try:
        amount = float((msg.text or "").strip())
    except ValueError:
        return await msg.answer("Invalid. Send a number:")
    if amount <= 0:
        return await msg.answer("Must be positive. Try again:")
    await state.update_data(deposit=amount)
    await state.set_state(Order.withdrawal)
    await msg.answer("Enter Withdrawal Amount (numbers only):")


@dp.message(Order.withdrawal)
async def ord_withdrawal(msg: types.Message, state: FSMContext):
    try:
        amount = float((msg.text or "").strip())
    except ValueError:
        return await msg.answer("Invalid. Send a number:")
    if amount <= 0:
        return await msg.answer("Must be positive. Try again:")
    await state.update_data(withdrawal=amount, collected_proofs=[])
    await state.set_state(Order.proof_deposit)
    await msg.answer(
        "Now send 3 proofs:\n\n"
        "1. Deposit Proof (screenshot)\n"
        "2. Withdrawal Proof (screenshot)\n"
        "3. Game Stat (screenshot)\n\n"
        "Send Deposit Proof first:"
    )


# PROOF_SECTION_REMOVED


import asyncio

_proof_buffer = {}
_proof_timer = {}


async def _process_buffer(user_id, state):
    await asyncio.sleep(1.5)

    new_photos = _proof_buffer.pop(user_id, [])
    _proof_timer.pop(user_id, None)

    if not new_photos:
        return

    # Get already collected from state
    data = await state.get_data()
    collected = data.get("collected_proofs", [])

    # Add new photos
    collected = collected + new_photos
    await state.update_data(collected_proofs=collected)

    if len(collected) >= 3:
        await _finalize_order(user_id, state, collected[:3])
    else:
        await bot.send_message(
            user_id,
            f"Received {len(collected)}/3 proofs. Please send {3-len(collected)} more:"
        )


@dp.message(Order.proof_deposit, F.photo)
@dp.message(Order.proof_withdrawal, F.photo)
@dp.message(Order.proof_stat, F.photo)
async def ord_proof_collector(msg: types.Message, state: FSMContext):
    user_id = msg.from_user.id
    file_id = msg.photo[-1].file_id

    print(f"[PROOF] Photo received from user {user_id}")

    if user_id not in _proof_buffer:
        _proof_buffer[user_id] = []
    _proof_buffer[user_id].append(file_id)

    if user_id in _proof_timer:
        _proof_timer[user_id].cancel()

    _proof_timer[user_id] = asyncio.create_task(
        _process_buffer(user_id, state)
    )


async def _finalize_order(user_id, state, proofs):
    from aiogram.types import InputMediaPhoto

    data = await state.get_data()
    uid = data.get("user_id")
    category = data.get("category")
    url = data.get("url")
    game_uid = data.get("game_uid")
    deposit = data.get("deposit")
    withdrawal = data.get("withdrawal")

    p1, p2, p3 = proofs[0], proofs[1], proofs[2]

    row = q_one("SELECT COUNT(*) FROM orders")
    count = (row[0] if row else 0) + 1
    order_no = f"ORD{count:03d}"

    urow = q_one("SELECT name, mobile FROM users WHERE id=?", (uid,))
    user_name = urow[0] if urow else "Unknown"
    user_mobile = urow[1] if urow else "Unknown"

    caption = (
        f"Order {order_no}\n"
        f"Category: {category}\n"
        f"User: {user_name}\n"
        f"Mobile: {user_mobile}\n"
        f"URL: {url}\n"
        f"Game UID: {game_uid}\n"
        f"Deposit: Rs {deposit}\n"
        f"Withdrawal: Rs {withdrawal}"
    )

    try:
        media = [
            InputMediaPhoto(media=p1, caption=caption),
            InputMediaPhoto(media=p2),
            InputMediaPhoto(media=p3),
        ]
        await bot.send_media_group(chat_id=PROOF_CHANNEL_ID, media=media)
        print(f"[ORDER] {order_no} album sent")
    except Exception as e:
        print(f"[ORDER ALBUM ERROR] {type(e).__name__}: {e}")

    q_exec(
        "INSERT INTO orders(order_no, user_id, category, url, game_uid, deposit, withdrawal, "
        "proof_deposit, proof_withdrawal, proof_stat, status) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,'pending')",
        (order_no, uid, category, url, game_uid, deposit, withdrawal, p1, p2, p3)
    )

    _proof_buffer.pop(user_id, None)
    _proof_timer.pop(user_id, None)

    await state.clear()
    await bot.send_message(
        user_id,
        f"Order Submitted\n\n"
        f"Order No: {order_no}\n"
        f"Category: {category}\n"
        f"Deposit: Rs {deposit}\n"
        f"Withdrawal: Rs {withdrawal}\n\n"
        f"Status: Pending\n"
        f"Admin will verify."
    )


@dp.message(Order.proof_deposit)
@dp.message(Order.proof_withdrawal)
@dp.message(Order.proof_stat)
async def ord_proof_wrong_type(msg: types.Message, state: FSMContext):
    await msg.answer("Please send a PHOTO (screenshot), not text.")


async def main():
    log.info("Slotex bot starting...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
