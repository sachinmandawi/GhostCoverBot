# -*- coding: utf-8 -*-
"""
GhostCoverBot - Full feature set (updated)
- Indian time (IST) support
- Date format: DD-MMM-YYYY (e.g., 30-Oct-2025)
- Time format: 12-hour with AM/PM (e.g., 12:00 AM)
- Date and time stored/displayed separately while internal logic uses ISO YYYY-MM-DD
- Coupon generation (owner) and redemption (user)
- Detailed referral list view with Share button
- Simplified "Refer & Earn" main panel
- Full Owner Panel & Daily Bonus button logic
- Removed Daily Bonus from Withdrawal panel
- Daily Bonus "already claimed" sends a new message
- Removed bolding from Refer & Earn panel stats
- Added Fake Leaderboard with Indian names (removed simulation text)
- Stake info revealed only when balance >= 2000 (Updated messaging)
- Multilingual Help Section (English/Hinglish) - Fixed language switching
- Owner panel: View/Process Withdrawals, Modify User Balance/Stake, Command List
- Reset user stats (streak, stake) after successful withdrawal request
- NEW: Owner panel export user stats as CSV (with username)
"""
import json
import os
import csv  # <-- Added for stats export
import io   # <-- Added for stats export
import datetime
import asyncio
import random
import string
import urllib.parse
from typing import Tuple

import pytz

from telegram import (
    CallbackQuery, # <-- Import CallbackQuery for type hinting
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ================ CONFIG =================
BOT_TOKEN = "8001331074:AAH5XJdjO3xsCqYSQptxO8mIjRpPK9-fI5E"  # <--- replace with your bot token
OWNER_ID = 8070535163  # <--- replace if needed
DATA_FILE = "data.json"
# =========================================

# Timezone: Indian Standard Time
IST = pytz.timezone("Asia/Kolkata")

WELCOME_TEXT = (
    "👻 Hey there! I’m GhostCoverBot\n\n"
    "🔹 I hide your identity like a pro.\n"
    "🔹 Just send me any message — text, photo, or video.\n"
    "🔹 I’ll instantly send it back without forward tag!\n\n"
    "📤 Forward it anywhere — people will think I sent it!"
)

DEFAULT_DATA = {
    "subscribers": [],
    "owners": [OWNER_ID],
    "force": {"enabled": False, "channels": [], "check_btn_text": "✅ I've Joined"},
    "users": {},
    "coupons": {},  # Stores {"CODE": {"amount": 100, "status": "active", ...}}
}

# --- Help Texts ---
HELP_TEXT_EN = (
    "💬 *Help & Info*\n\n"
    "👻 This bot helps you send anonymous messages without revealing your identity.\n\n"
    "❓ **How it works:**\n"
    "1. Send any message (text, photo, video) directly to me.\n"
    "2. I will immediately send it back to you without any 'forwarded from' tag.\n"
    "3. You can then forward this new message anywhere (chats, groups, channels), and it will look like the bot sent it, not you!\n\n"
    "💸 **Earning & Rewards:**\n"
    "• Use *Refer & Earn* to get your unique link. Earn ₹100 for your first referral and ₹10 for every referral after that. The new user also gets the same amount!\n"
    "• Claim your *Daily Bonus* (₹10) every calendar day (after 12:00 AM IST). Maintain a 7-day streak for an extra ₹100 bonus!\n"
    "• Redeem *Coupons* shared by the owner for extra balance.\n\n"
    "🏁 **Withdrawal:**\n"
    "• First, your balance needs to reach ₹2000. This unlocks the *20-Day Invite Stake*.\n"
    "• Then, you must invite at least 1 new user each calendar day (after 12:00 AM IST) for 20 consecutive days. You earn ₹50 for each successful stake day invite.\n"
    "• Missing a day will deduct ₹100 and reset your stake progress!\n"
    "• Once the stake is complete AND your balance is still ₹2000 or more, you can request withdrawal.\n\n"
    "If you need anything else, contact the owner."
)

HELP_TEXT_HI = (
    "💬 *Madad & Jaankari*\n\n"
    "👻 Yeh bot aapki identity chupakar anonymous message bhejne mein madad karta hai.\n\n"
    "❓ **Kaise kaam karta hai:**\n"
    "1. Koi bhi message (text, photo, video) mujhe direct bhejein.\n"
    "2. Main turant use bina kisi 'forwarded from' tag ke aapko wapas bhej dunga.\n"
    "3. Aap fir is naye message ko kahin bhi forward kar sakte hain (chats, groups, channels), aur aisa lagega jaise bot ne bheja hai, aapne nahi!\n\n"
    "💸 **Earning & Inaam:**\n"
    "• *Refer & Earn* istemal karke apna unique link payein. Pehle referral ke liye ₹100 aur uske baad har referral ke liye ₹10 kamayein. Naye user ko bhi utna hi milta hai!\n"
    "• Apna *Daily Bonus* (₹10) har calendar din (raat 12:00 baje IST ke baad) claim karein. Lagatar 7 din claim karne par extra ₹100 bonus milega!\n"
    "• Owner dwara share kiye gaye *Coupons* redeem karke extra balance payein.\n\n"
    "🏁 **Withdrawal:**\n"
    "• Pehle, aapka balance ₹2000 tak pahunchna chahiye. Isse *20-Day Invite Stake* unlock hoga.\n"
    "• Fir, aapko lagatar 20 din tak har calendar din (raat 12:00 baje IST ke baad) kam se kam 1 naya user invite karna hoga. Har safal stake din ke invite par ₹50 milenge.\n"
    "• Ek din miss karne par ₹100 kat jayenge aur aapka stake progress reset ho jayega!\n"
    "• Jab stake poora ho jaye AUR aapka balance abhi bhi ₹2000 ya usse zyada ho, tab aap withdrawal request kar sakte hain.\n\n"
    "Agar aapko kuch aur chahiye, toh owner se contact karein."
)

# --- Owner Command List ---
OWNER_COMMAND_LIST = """
📚 *Owner Panel Commands*

*Main Panel:*
• *Broadcast:* Send a message to all users.
• *Generate Coupon:* Create a redeemable coupon code.
• *Force Join Setting:* Manage required channels.
• *Manage Owner:* Add or remove bot owners.
• *View Withdrawals:* See and process pending requests.
• *Modify User:* Change a specific user's balance or stake.
• *Export User Stats:* Get a CSV file of all user data.
• *Command List:* Show this help message.
• *Close:* Close the owner panel.

*Modify User Sub-Panel:*
• *Modify Balance:* Set balance using `+Amount`, `-Amount`, or `=Amount`.
• *Modify Stake:* Set completed stake days (0-20).
• *Show User Info:* Display user's current stats.
"""


# ---------------- Time helpers ----------------
def _today_date_str() -> str:
    """Return today's date in IST as DD-MMM-YYYY (e.g., 30-Oct-2025)."""
    return datetime.datetime.now(IST).strftime("%d-%b-%Y")


def _now_time_str() -> str:
    """Return current time in IST in 12-hour format with AM/PM (e.g., 12:00 AM)."""
    return datetime.datetime.now(IST).strftime("%I:%M %p")


def _today_iso() -> str:
    """Return ISO date YYYY-MM-DD for internal logic where needed."""
    return datetime.datetime.now(IST).date().isoformat()


# ---------------- Storage Helpers ----------------
def load_data() -> dict:
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_DATA, f, indent=2)
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    if "force" not in data:
        data["force"] = DEFAULT_DATA["force"]
    if "owners" not in data:
        data["owners"] = DEFAULT_DATA["owners"]
    if "subscribers" not in data:
        data["subscribers"] = DEFAULT_DATA["subscribers"]
    if "users" not in data:
        data["users"] = {}
    if "coupons" not in data:
        data["coupons"] = {}
    return data


def save_data(data: dict):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def is_owner(uid: int) -> bool:
    data = load_data()
    return uid in data.get("owners", [])


# ---------------- Coupon helper ----------------
def _generate_coupon_code(data: dict, length: int = 8) -> str:
    """Generates a unique GHOST-XXXX... code."""
    coupons = data.get("coupons", {})
    chars = string.ascii_uppercase + string.digits
    while True:
        code_part = "".join(random.choices(chars, k=length))
        code = f"GHOST-{code_part}"
        if code not in coupons:
            return code


# ---------------- User record helpers ----------------
def ensure_user_record(data: dict, uid: int, username: str = None) -> dict:
    """Ensures user record exists and returns it. Stores username on creation."""
    key = str(uid)
    if key not in data.setdefault("users", {}):
        data["users"][key] = {
            "username": username or f"ID_{uid}", # <-- Stores username
            "balance": 0,
            "referrals": [],
            "referred_by": None,
            "last_daily": "",  # internal ISO YYYY-MM-DD
            "last_daily_display": "",  # DD-MMM-YYYY for display
            "last_daily_time": "",  # hh:mm AM/PM
            "daily_streak": 0,
            # stake / withdrawal fields
            "withdrawal_unlocked": False,  # set when user first reaches >=2000 (sticky)
            "stake_active": False,
            "stake_start_date": "",  # display DD-MMM-YYYY
            "stake_start_date_iso": "",  # ISO YYYY-MM-DD for logic
            "stake_days_completed": 0,
            "stake_last_invite_date": "",  # ISO YYYY-MM-DD (for gap math)
            "stake_last_invite_date_display": "",  # DD-MMM-YYYY (for user)
            "stake_last_invite_time": "",  # hh:mm AM/PM
            "stake_completed": False,
            "pending_withdrawal": None,
        }
    return data["users"][key]


def get_user_record(data: dict, uid: int) -> dict:
    return data.get("users", {}).get(str(uid))


def award_balance(data: dict, uid: int, amount: int) -> bool:
    """
    Increase user's balance by amount.
    Returns True if this addition caused FIRST-TIME crossing of 2000
    (i.e., unlock stake/withdrawal). This does NOT send messages.
    """
    rec = ensure_user_record(data, uid) # Will fetch existing record
    prev = int(rec.get("balance", 0))
    rec["balance"] = prev + int(amount)
    revealed = False
    # Unlock stake internally on first crossing of 2000 (sticky)
    if prev < 2000 <= rec["balance"] and not rec.get("withdrawal_unlocked", False):
        rec["withdrawal_unlocked"] = True
        # store both ISO and display
        iso_today = _today_iso()
        rec["stake_start_date_iso"] = iso_today
        rec["stake_start_date"] = _today_date_str()
        rec["stake_active"] = True
        rec["stake_days_completed"] = 0
        rec["stake_last_invite_date"] = ""
        rec["stake_last_invite_date_display"] = ""
        rec["stake_last_invite_time"] = ""
        rec["stake_completed"] = False
        revealed = True # This flag isn't used anymore, but keep for now
    save_data(data)
    return revealed


# ---------------- Stake processing (calendar-day based) ----------------
def process_referrer_stake_on_new_invite(data: dict, ref_id: int, context: ContextTypes.DEFAULT_TYPE = None):
    """
    Called when referrer `ref_id` gets a new referred user (i.e., new user used their ref link).
    Counting rules (calendar day IST):
    - If no previous counted invite date -> count as day 1 (award 50)
    - If last counted invite date is same day -> ignore (already counted today)
    - If last counted invite date is yesterday (gap == 1) -> count this day, award 50
    - If gap > 1 -> missed window -> deduct 100, reset stake_active False, reset counters
    - If stake_days_completed reaches 20 -> stake_completed True, stake_active False
    Notifications are sent if `context` provided (best-effort, non-blocking).
    """
    rec = ensure_user_record(data, ref_id)
    if not rec.get("stake_active", False):
        return

    today_dt = datetime.datetime.now(IST).date()
    today_iso = today_dt.isoformat()
    today_display = today_dt.strftime("%d-%b-%Y")
    now_time = _now_time_str()

    last_s = rec.get("stake_last_invite_date", "") or None

    async def _notify(uid: int, text: str):
        if context is None:
            return
        try:
            await context.bot.send_message(uid, text, parse_mode="Markdown")
        except Exception:
            pass

    if not last_s:
        # first counted invite
        rec["stake_days_completed"] = 1
        rec["stake_last_invite_date"] = today_iso
        rec["stake_last_invite_date_display"] = today_display
        rec["stake_last_invite_time"] = now_time
        award_balance(data, ref_id, 50)  # award ₹50 for counted invite
        save_data(data)
        # notify async
        if context is not None:
            asyncio.create_task(_notify(ref_id,
                                        f"🎉 Invite counted! You earned ₹50. Stake progress: {rec['stake_days_completed']}/20\nDate: {today_display}\nTime: {now_time}"))
        if rec["stake_days_completed"] >= 20:
            rec["stake_completed"] = True
            rec["stake_active"] = False
            save_data(data)
        return

    try:
        last_date = datetime.date.fromisoformat(last_s)
    except Exception:
        # malformed date -> reset stake
        rec["stake_active"] = False
        rec["stake_days_completed"] = 0
        rec["stake_last_invite_date"] = ""
        rec["stake_last_invite_date_display"] = ""
        rec["stake_last_invite_time"] = ""
        rec["stake_completed"] = False
        save_data(data)
        return

    gap = (today_dt - last_date).days

    if gap == 0:
        # already counted today -> ignore
        return
    elif gap == 1:
        # valid next-day invite -> count
        rec["stake_days_completed"] = int(rec.get("stake_days_completed", 0)) + 1
        rec["stake_last_invite_date"] = today_iso
        rec["stake_last_invite_date_display"] = today_display
        rec["stake_last_invite_time"] = now_time
        award_balance(data, ref_id, 50)  # award ₹50
        save_data(data)
        if context is not None:
            asyncio.create_task(_notify(ref_id,
                                        f"🎉 Invite counted! You earned ₹50. Stake progress: {rec['stake_days_completed']}/20\nDate: {today_display}\nTime: {now_time}"))
        if rec["stake_days_completed"] >= 20:
            rec["stake_completed"] = True
            rec["stake_active"] = False
            save_data(data)
        return
    else:
        # missed window -> penalty and reset
        bal = int(rec.get("balance", 0))
        new_bal = max(0, bal - 100)
        rec["balance"] = new_bal
        rec["stake_active"] = False
        rec["stake_days_completed"] = 0
        rec["stake_last_invite_date"] = ""
        rec["stake_last_invite_date_display"] = ""
        rec["stake_last_invite_time"] = ""
        rec["stake_completed"] = False
        save_data(data)
        if context is not None:
            asyncio.create_task(_notify(ref_id,
                                        f"⚠️ You missed a day. ₹100 has been deducted as penalty and your 20-day stake has been reset. Current balance: ₹{new_bal}"))
        return


# ---------------- Force-join helpers (kept minimal) ----------------
def _normalize_channel_entry(raw):
    if isinstance(raw, dict):
        return {
            "chat_id": raw.get("chat_id") or raw.get("chat") or None,
            "invite": raw.get("invite") or raw.get("url") or None,
            "join_btn_text": raw.get("join_btn_text") or raw.get("button") or None,
        }
    if isinstance(raw, str):
        text = raw.strip()
        if text.startswith("http://") or text.startswith("https://"):
            return {"chat_id": None, "invite": text, "join_btn_text": None}
        else:
            return {"chat_id": text, "invite": None, "join_btn_text": None}
    return {"chat_id": None, "invite": None, "join_btn_text": None}


def _derive_query_chat_from_entry(ch):
    chat_id = ch.get("chat_id")
    invite = ch.get("invite")
    if chat_id:
        return chat_id
    if invite and "t.me/" in invite:
        parts = invite.rstrip("/").split("/")
        possible = parts[-1] if parts else ""
        if possible and not possible.lower().startswith(("joinchat", "+")):
            return possible if possible.startswith("@") else f"@{possible}"
    return None


async def get_missing_channels(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> Tuple[list, bool]:
    data = load_data()
    force = data.get("force", {})
    raw_channels = force.get("channels", []) or []
    normalized = [_normalize_channel_entry(c) for c in raw_channels]
    if not normalized:
        return [], False
    any_check_attempted = False
    any_check_succeeded = False
    missing = []
    for ch in normalized:
        query_chat = _derive_query_chat_from_entry(ch)
        if query_chat:
            try:
                any_check_attempted = True
                member = await context.bot.get_chat_member(chat_id=query_chat, user_id=user_id)
                any_check_succeeded = True
                if member.status in ("left", "kicked"):
                    missing.append(ch)
            except Exception:
                missing.append(ch)
                continue
        else:
            missing.append(ch)
    check_failed = not any_check_attempted and any_check_succeeded is False
    return missing, check_failed


def build_join_keyboard_for_channels_list(ch_list, force_cfg):
    buttons = []
    for ch in ch_list:
        join_label = ch.get("join_btn_text") or "🔗 Join Channel"
        if ch.get("invite"):
            try:
                btn = InlineKeyboardButton(join_label, url=ch["invite"])
            except Exception:
                btn = InlineKeyboardButton(join_label, callback_data="force_no_invite")
        else:
            chat = ch.get("chat_id") or ""
            if chat and chat.startswith("@"):
                btn = InlineKeyboardButton(join_label, url=f"https://t.me/{chat.lstrip('@')}")
            else:
                btn = InlineKeyboardButton(join_label, callback_data="force_no_invite")
        buttons.append(btn)
    rows = []
    i = 0
    while i < len(buttons):
        if i + 1 < len(buttons):
            rows.append([buttons[i], buttons[i + 1]])
            i += 2
        else:
            rows.append([buttons[i]])
            i += 1
    check_label = force_cfg.get("check_btn_text") or "✅ I've Joined"
    rows.append([InlineKeyboardButton(check_label, callback_data="check_join")])
    return InlineKeyboardMarkup(rows)


async def prompt_user_with_missing_channels(update: Update, context: ContextTypes.DEFAULT_TYPE,
                                            missing_norm_list, check_failed=False):
    if not missing_norm_list:
        if check_failed:
            if update.callback_query:
                await update.callback_query.message.reply_text(
                    "⚠️ I couldn't verify memberships (bot may not have access). Owner, please check bot permissions.")
            else:
                await update.message.reply_text(
                    "⚠️ I couldn't verify memberships (bot may not have access). Owner, please check bot permissions.")
        else:
            if update.callback_query:
                await update.callback_query.message.reply_text("✅ You seem to be a member of all channels.")
            else:
                await update.message.reply_text("✅ You seem to be a member of all channels.")
        return

    total = len(load_data().get("force", {}).get("channels", []))
    missing_count = len(missing_norm_list)
    joined_count = max(0, total - missing_count)

    if joined_count == 0:
        text = (
            "🔒 *Access Restricted*\n\n"
            "You need to join the required channels before using the bot.\n\n"
            "Tap each **Join** button below, join those channels, and then press **Verify** to continue."
        )
    else:
        text = (
            "🔒 *Access Restricted*\n\n"
            "You’ve joined some channels, but a few are still left.\n\n"
            "Tap the **Join** buttons below for the remaining channels, then press **Verify** once done."
        )

    kb = build_join_keyboard_for_channels_list(missing_norm_list, load_data().get("force", {}))
    if update.callback_query:
        await update.callback_query.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)
    else:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)


# ---------------- Keyboards ----------------
def owner_panel_kb():
    kb = [
        [InlineKeyboardButton("📢 Broadcast", callback_data="owner_broadcast"),
         InlineKeyboardButton("🎁 Generate Coupon", callback_data="owner_coupon")],
        [InlineKeyboardButton("🔒 Force Join Setting", callback_data="owner_force"),
         InlineKeyboardButton("🧑‍💼 Manage Owner", callback_data="owner_manage")],
        [InlineKeyboardButton("⏳ View Withdrawals", callback_data="owner_view_withdrawals"),
         InlineKeyboardButton("⚙️ Modify User", callback_data="owner_modify_user")],
        [InlineKeyboardButton("📊 Export User Stats", callback_data="owner_export_stats")], # <-- New button
        [InlineKeyboardButton("📚 Command List", callback_data="owner_cmd_list")],
        [InlineKeyboardButton("⬅️ Close", callback_data="owner_close")],
    ]
    return InlineKeyboardMarkup(kb)


def force_setting_kb(force: dict):
    kb = [
        [InlineKeyboardButton("🔁 Toggle Force-Join", callback_data="force_toggle"),
         InlineKeyboardButton("➕ Add Channel", callback_data="force_add")],
        [InlineKeyboardButton("🗑️ Remove Channel", callback_data="force_remove"),
         InlineKeyboardButton("📜 List Channel", callback_data="force_list")],
        [InlineKeyboardButton("⬅️ Back", callback_data="force_back")],
    ]
    return InlineKeyboardMarkup(kb)


def cancel_btn():
    return ReplyKeyboardMarkup([["❌ Cancel"]], resize_keyboard=True)

# --- Fake Leaderboard Data ---
_fake_indian_names = [
    "Aarav", "Vihaan", "Aditya", "Sai", "Aryan", "Arjun", "Reyansh", "Krishna", "Ishaan", "Rudra",
    "Aanya", "Saanvi", "Aadya", "Ananya", "Pari", "Diya", "Myra", "Kiara", "Siya", "Ishita",
    "Sachin", "Priya", "Amit", "Neha", "Rahul", "Pooja", "Sandeep", "Kavita", "Vikas", "Sunita",
    "Deepak", "Anjali", "Rajesh", "Meena", "Suresh", "Geeta", "Manoj", "Rekha", "Anil", "Usha"
]

def _generate_fake_username():
    return random.choice(_fake_indian_names)

def _generate_fake_leaderboard_data():
    # Top Referrers
    referrers = []
    used_names = set() # Ensure unique names for top referrers
    while len(referrers) < 5:
        name = _generate_fake_username()
        if name not in used_names:
            count = random.randint(50, 500)
            referrers.append({"name": name, "count": count})
            used_names.add(name)
    referrers.sort(key=lambda x: x["count"], reverse=True) # Sort descending

    # Recent Withdrawals
    withdrawals = []
    for _ in range(3):
        name = _generate_fake_username() # Names can repeat here
        amount = random.randint(2000, 10000)
        withdrawals.append({"name": name, "amount": amount})
    
    return referrers, withdrawals


# ---------------- Commands ----------------
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    data = load_data()

    # parse referral arg (deep link)
    referral_arg = None
    if context.args:
        referral_arg = context.args[0]
    if not referral_arg and update.message and update.message.text:
        parts = update.message.text.split()
        if len(parts) > 1:
            referral_arg = parts[1]

    # ensure record, passing username
    rec = ensure_user_record(data, user.id, user.username)

    # Also update username if it has changed
    if user.username:
        rec["username"] = user.username

    # process referral if applicable (and not self-referral)
    if referral_arg and rec.get("referred_by") is None:
        try:
            ref_id = int(referral_arg)
            if ref_id != user.id:
                ref_rec = ensure_user_record(data, ref_id) # Don't need to pass username here
                if str(user.id) not in [str(x) for x in ref_rec.get("referrals", [])]:
                    prev_count = len(ref_rec.get("referrals", []))
                    amt = 100 if prev_count == 0 else 10

                    # award both via award_balance (detect crossing 2000)
                    award_balance(data, ref_id, amt) # We don't need the return value anymore
                    award_balance(data, user.id, amt)

                    # record referral
                    ref_rec.setdefault("referrals", []).append(user.id)
                    rec["referred_by"] = ref_id
                    save_data(data)

                    # process stake counting for referrer (this may award +50 if day counts)
                    process_referrer_stake_on_new_invite(data, ref_id, context)

                    # notify earnings (best-effort)
                    try:
                        await context.bot.send_message(ref_id,
                                                       f"🎉 You referred a user! You earned ₹{amt}. Total balance: ₹{ensure_user_record(data, ref_id)['balance']}")
                    except Exception:
                        pass
                    try:
                        await context.bot.send_message(user.id,
                                                       f"🎉 You were referred! You received ₹{amt}. Total balance: ₹{ensure_user_record(data, user.id)['balance']}")
                    except Exception:
                        pass

        except Exception:
            pass

    # Force-join checks for non-owners
    if not is_owner(user.id):
        force = data.get("force", {})
        if force.get("enabled", False):
            if force.get("channels"):
                missing, check_failed = await get_missing_channels(context, user.id)
                if not missing:
                    subs = data.setdefault("subscribers", [])
                    if user.id not in subs:
                        subs.append(user.id)
                        save_data(data)
                else:
                    subs = data.setdefault("subscribers", [])
                    if user.id in subs:
                        subs.remove(user.id)
                        save_data(data)
                    await prompt_user_with_missing_channels(update, context, missing, check_failed)
                    return
            else:
                await update.message.reply_text(
                    "⚠️ Force-Join is enabled but no channels are configured. Owner, please configure channels via /owner.")
                return

    subs = data.setdefault("subscribers", [])
    if user.id not in subs:
        subs.append(user.id)
    ensure_user_record(data, user.id, user.username) # Ensure again (harmless)
    save_data(data)

    # prepare referral link and keyboard
    try:
        me = await context.bot.get_me()
        bot_user = me.username or "thisbot"
        ref_link = f"https://t.me/{bot_user}?start={user.id}"
    except Exception:
        ref_link = f"/start {user.id}"

    # welcome with two inline buttons
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🎁 Refer & Earn", callback_data="show_earn"),
             InlineKeyboardButton("💬 Help", callback_data="show_help")]
        ]
    )
    await update.message.reply_text(WELCOME_TEXT, reply_markup=kb)


async def owner_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("❌ Only owners can access this panel.")
        return
    await update.message.reply_text("🔧 *Owner Panel*\n\nChoose an option:", parse_mode="Markdown",
                                    reply_markup=owner_panel_kb())


# ---------------- Daily command ----------------
async def daily_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id
    data = load_data()
    rec = ensure_user_record(data, uid)

    today_dt = datetime.datetime.now(IST).date()
    today_iso = today_dt.isoformat()
    today_display = today_dt.strftime("%d-%b-%Y")
    now_time = _now_time_str()

    last_daily_s = rec.get("last_daily", "")
    last_daily_date = None
    if last_daily_s:
        try:
            last_daily_date = datetime.date.fromisoformat(last_daily_s)
        except Exception:
            last_daily_date = None

    if last_daily_s == today_iso:
        await update.message.reply_text("✅ You already claimed today's Daily Bonus.")
        return

    gap = None
    if last_daily_date:
        gap = (today_dt - last_daily_date).days

    # penalty for missing >1 day (half balance)
    if gap is not None and gap > 1:
        old_balance = int(rec.get("balance", 0))
        new_balance = old_balance // 2
        rec["balance"] = new_balance
        rec["daily_streak"] = 0
        # award today's daily using award_balance
        award_balance(data, uid, 10)
        rec = ensure_user_record(data, uid) # Re-fetch after balance change
        rec["last_daily"] = today_iso
        rec["last_daily_display"] = today_display
        rec["last_daily_time"] = now_time
        rec["daily_streak"] = 1
        save_data(data)
        await update.message.reply_text(
            f"⚠️ You missed {gap - 1} day(s). Your balance was halved from ₹{old_balance} to ₹{new_balance}.\n"
            f"You received today's Daily Bonus: ₹10.\nDate: {rec['last_daily_display']}\nTime: {rec['last_daily_time']}\nCurrent balance: ₹{rec['balance']}\nStreak reset to 1."
        )
        return

    # continue or start streak
    if gap == 1:
        rec["daily_streak"] = int(rec.get("daily_streak", 0)) + 1
    else:
        rec["daily_streak"] = 1

    award_balance(data, uid, 10)
    rec = ensure_user_record(data, uid) # Re-fetch after balance change
    rec["last_daily"] = today_iso
    rec["last_daily_display"] = today_display
    rec["last_daily_time"] = now_time

    if rec["daily_streak"] >= 7:
        # award 7-day bonus
        award_balance(data, uid, 100)
        rec = ensure_user_record(data, uid) # Re-fetch after balance change
        rec["daily_streak"] = 0 # Reset streak
        save_data(data)
        await update.message.reply_text(
            f"🎉 You completed a 7-day streak! You received ₹10 for today + ₹100 streak bonus.\nDate: {rec['last_daily_display']}\nTime: {rec['last_daily_time']}\nCurrent balance: ₹{rec['balance']}"
        )
        return

    save_data(data)
    await update.message.reply_text(
        f"✅ Daily Bonus claimed: ₹10.\nDate: {rec['last_daily_display']}\nTime: {rec['last_daily_time']}\nCurrent streak: {rec['daily_streak']} day(s).\nBalance: ₹{rec['balance']}"
    )


# ---------------- Claim daily via callback ----------------
async def handle_claim_daily_query(query, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles the logic for claiming a daily bonus.
    Assumes the "already claimed" check was done BEFORE calling this.
    """
    await query.answer() # Answer query immediately
    uid = query.from_user.id
    data = load_data()
    rec = ensure_user_record(data, uid)

    today_dt = datetime.datetime.now(IST).date()
    today_iso = today_dt.isoformat()
    today_display = today_dt.strftime("%d-%b-%Y")
    now_time = _now_time_str()

    last_daily_s = rec.get("last_daily", "")
    last_daily_date = None
    if last_daily_s:
        try:
            last_daily_date = datetime.date.fromisoformat(last_daily_s)
        except Exception:
            last_daily_date = None

    # This check is now done in callback_handler, but we'll leave it
    # as a safeguard in case /daily is used.
    if last_daily_s == today_iso:
        try:
            await query.answer("✅ You already claimed today's Daily Bonus.", show_alert=True)
        except Exception:
            pass
        return

    gap = None
    if last_daily_date:
        gap = (today_dt - last_daily_date).days

    if gap is not None and gap > 1:
        old_balance = int(rec.get("balance", 0))
        new_balance = old_balance // 2
        rec["balance"] = new_balance
        rec["daily_streak"] = 0
        award_balance(data, uid, 10)
        rec = ensure_user_record(data, uid) # Re-fetch after balance change
        rec["last_daily"] = today_iso
        rec["last_daily_display"] = today_display
        rec["last_daily_time"] = now_time
        rec["daily_streak"] = 1
        save_data(data)
        try:
            # Edit the main panel text instead of replying
            await query.message.edit_text(
                f"⚠️ You missed {gap - 1} day(s). Your balance was halved from ₹{old_balance} to ₹{new_balance}.\n"
                f"You received today's Daily Bonus: ₹10.\nDate: {rec['last_daily_display']}\nTime: {rec['last_daily_time']}\nCurrent balance: ₹{rec['balance']}\nStreak reset to 1.\n\n"
                f"Panel will refresh in 5 seconds..."
            )
        except Exception:
            await query.answer("Daily processed. Check chat.")
        
        # Schedule a task to show the main earn panel again
        asyncio.create_task(refresh_earn_panel(query, context, delay=5))
        return

    if gap == 1:
        rec["daily_streak"] = int(rec.get("daily_streak", 0)) + 1
    else:
        rec["daily_streak"] = 1

    award_balance(data, uid, 10)
    rec = ensure_user_record(data, uid) # Re-fetch after balance change
    rec["last_daily"] = today_iso
    rec["last_daily_display"] = today_display
    rec["last_daily_time"] = now_time

    if rec["daily_streak"] >= 7:
        award_balance(data, uid, 100)
        rec = ensure_user_record(data, uid) # Re-fetch after balance change
        rec["daily_streak"] = 0 # Reset streak
        save_data(data)
        try:
            await query.message.edit_text(
                f"🎉 You completed a 7-day streak! You received ₹10 for today + ₹100 streak bonus.\nDate: {rec['last_daily_display']}\nTime: {rec['last_daily_time']}\nCurrent balance: ₹{rec['balance']}\n\n"
                f"Panel will refresh in 5 seconds..."
            )
        except Exception:
            await query.answer("7-day streak processed. Check chat.")
        
        asyncio.create_task(refresh_earn_panel(query, context, delay=5))
        return

    save_data(data)
    try:
        await query.message.edit_text(
            f"✅ Daily Bonus claimed: ₹10.\nDate: {rec['last_daily_display']}\nTime: {rec['last_daily_time']}\nCurrent streak: {rec['daily_streak']} day(s). Balance: ₹{rec['balance']}\n\n"
            f"Panel will refresh in 5 seconds..."
        )
    except Exception:
        await query.answer("Daily processed. Check chat.")
    
    asyncio.create_task(refresh_earn_panel(query, context, delay=5))


async def refresh_earn_panel(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, delay: int = 0): # Changed type hint
    """Helper to wait and then show the 'show_earn' panel again."""
    if delay > 0:
        await asyncio.sleep(delay)
    
    # Simulate a new callback query for 'show_earn'
    # We need to reuse the original query's message to edit it
    uid = query.from_user.id
    data = load_data()
    rec = ensure_user_record(data, uid)
    try:
        me = await context.bot.get_me()
        bot_user = me.username or "thisbot"
        ref_link = f"https.t.me/{bot_user}?start={uid}"
    except Exception:
        ref_link = f"/start {uid}"

    bal = int(rec.get("balance", 0))
    refs = rec.get("referrals", [])
    streak = rec.get("daily_streak", 0)
    last = rec.get("last_daily_display", "Never")
    last_time = rec.get("last_daily_time", "—")

    text = (
        f"💸 *Refer & Earn*\n\n"
        f"💰 Balance: ₹{bal}\n"
        f"📣 Referrals: {len(refs)}\n"
        f"🔥 Daily streak: {streak}\n"
        f"📅 Last daily: {last} at {last_time}"
    )
    
    # Show stake info only if balance is currently >= 2000
    if bal >= 2000:
        stake_active = rec.get("stake_active", False)
        stake_days = rec.get("stake_days_completed", 0)
        stake_start = rec.get("stake_start_date", "—")
        stake_status = "Completed" if rec.get("stake_completed", False) else ("Active" if stake_active else "Inactive/Starting")
        
        text += (
            f"\n\n🏁 *20-Day Invite Stake:* {stake_status}\n"
            f"• Start Date (approx): {stake_start}\n" # Mention approx start
            f"• Progress: {stake_days}/20\n\n"
            "🔒 *Reminder:* You also need ₹2000+ balance when requesting withdrawal."
        )

    kb_rows = [
        [InlineKeyboardButton("🔗 My Referral Link & Details", callback_data="show_ref_details")],
        [InlineKeyboardButton("🎯 Daily Bonus", callback_data="claim_daily"),
         InlineKeyboardButton("🏆 Leaderboard", callback_data="show_leaderboard")],
        [InlineKeyboardButton("🎁 Redeem Coupon", callback_data="redeem_coupon"),
         InlineKeyboardButton("💸 Withdrawal", callback_data="withdraw_panel")],
        [InlineKeyboardButton("❌ Close", callback_data="earn_close")],
    ]
    kb = InlineKeyboardMarkup(kb_rows)
    
    try:
        # Edit the message from the original query
        await query.message.edit_text(text, parse_mode="Markdown", reply_markup=kb, disable_web_page_preview=True)
    except Exception:
        pass # Ignore if edit fails (e.g., user clicked elsewhere)


# ---------------- Stake status ----------------
async def stake_status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id
    data = load_data()
    rec = ensure_user_record(data, uid)
    bal = int(rec.get("balance", 0))

    # Use balance check first
    if bal < 2000:
        await update.message.reply_text(
            f"💰 Your current balance is ₹{bal}.\n\nKeep earning to unlock more features!") # Updated message
        return

    # If balance is >= 2000, show the detailed status
    active = rec.get("stake_active", False)
    completed = rec.get("stake_completed", False)
    days = rec.get("stake_days_completed", 0)
    start = rec.get("stake_start_date", "—")
    last = rec.get("stake_last_invite_date_display", "—")
    last_time = rec.get("stake_last_invite_time", "—")

    if completed:
        await update.message.reply_text(f"🎉 You completed the 20-day stake! Days: 20/20 ✅")
        return

    if not active and rec.get("withdrawal_unlocked"): # Only show inactive if they ever unlocked it
        await update.message.reply_text("⚠️ Your stake is currently inactive (possibly due to missing a day). Keep inviting daily to continue or restart.")
        return
        
    # Default message if active
    await update.message.reply_text(
        f"🔥 *20-Day Invite Stake*\nStart: {start}\nCompleted days: {days}/20\nLast counted invite: {last} at {last_time}\nStatus: Active",
        parse_mode="Markdown",
    )

# --- Help logic helper function ---
async def show_help_logic(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE):
    """Refactored logic to display help message based on context.user_data."""
    current_lang = context.user_data.get('language', 'en')
    help_text = HELP_TEXT_HI if current_lang == 'hi' else HELP_TEXT_EN

    if current_lang == 'hi':
        lang_button = InlineKeyboardButton("🇬🇧 English", callback_data="set_lang_en")
    else:
        lang_button = InlineKeyboardButton("🇮🇳 Hinglish", callback_data="set_lang_hi")

    kb = InlineKeyboardMarkup([
        [lang_button],
        [InlineKeyboardButton("⬅️ Back", callback_data="show_earn")]
    ])

    try:
        await query.message.edit_text(help_text, parse_mode="Markdown", reply_markup=kb)
    except Exception:
         # Fallback if edit fails
        await query.message.reply_text(help_text, parse_mode="Markdown", reply_markup=kb)
# --- End of helper function ---

# ---------------- Callback handler ----------------
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    # Answer query immediately, unless it's the daily bonus logic (handled inside)
    if query.data != "claim_daily":
        await query.answer() 
    
    uid = query.from_user.id
    payload = query.data
    data = load_data()
    # No need to get current_lang here, get it inside show_help_logic

    # --- Generic Callbacks ---
    if payload == "noop":
        await query.answer("This action is not allowed.", show_alert=True)
        return

    # owner close
    if payload == "owner_close":
        await query.answer()
        try:
            await query.message.edit_text("✅ Owner panel closed.")
        except Exception:
            await query.message.delete()
        return

    # Help section with language support
    if payload == "show_help":
        await show_help_logic(query, context) # Call the helper function
        return

    # Set language callbacks
    if payload == "set_lang_en":
        context.user_data['language'] = 'en'
        await show_help_logic(query, context) # Call the helper function after setting lang
        return
        
    if payload == "set_lang_hi":
        context.user_data['language'] = 'hi'
        await show_help_logic(query, context) # Call the helper function after setting lang
        return

    # --- User Panel Callbacks ---

    # Show Refer & Earn panel
    if payload == "show_earn":
        rec = ensure_user_record(data, uid)
        bal = int(rec.get("balance", 0))
        refs = rec.get("referrals", [])
        streak = rec.get("daily_streak", 0)
        last = rec.get("last_daily_display", "Never")
        last_time = rec.get("last_daily_time", "—")

        text = (
            f"💸 *Refer & Earn*\n\n"
            f"💰 Balance: ₹{bal}\n"
            f"📣 Referrals: {len(refs)}\n"
            f"🔥 Daily streak: {streak}\n"
            f"📅 Last daily: {last} at {last_time}"
        )
        
        # Show stake info only if balance is currently >= 2000
        if bal >= 2000:
            stake_active = rec.get("stake_active", False)
            stake_days = rec.get("stake_days_completed", 0)
            stake_start = rec.get("stake_start_date", "—")
            # Determine status based on internal flags even if balance just crossed
            stake_status = "Completed" if rec.get("stake_completed", False) else ("Active" if stake_active else "Inactive/Starting")
            
            text += (
                f"\n\n🏁 *20-Day Invite Stake:* {stake_status}\n"
                f"• Start Date (approx): {stake_start}\n" # Mention approx start
                f"• Progress: {stake_days}/20\n\n"
                "🔒 *Reminder:* You also need ₹2000+ balance when requesting withdrawal."
            )

        kb_rows = [
            [InlineKeyboardButton("🔗 My Referral Link & Details", callback_data="show_ref_details")],
            [InlineKeyboardButton("🎯 Daily Bonus", callback_data="claim_daily"),
             InlineKeyboardButton("🏆 Leaderboard", callback_data="show_leaderboard")],
            [InlineKeyboardButton("🎁 Redeem Coupon", callback_data="redeem_coupon"),
             InlineKeyboardButton("💸 Withdrawal", callback_data="withdraw_panel")],
            [InlineKeyboardButton("❌ Close", callback_data="earn_close")],
        ]
        kb = InlineKeyboardMarkup(kb_rows)
        try:
            await query.message.edit_text(text, parse_mode="Markdown", reply_markup=kb, disable_web_page_preview=True)
        except Exception:
            await query.message.reply_text(text, parse_mode="Markdown", reply_markup=kb, disable_web_page_preview=True)
        return

    # Close
    if payload == "earn_close":
        try:
            await query.message.edit_text("✅ Closed.")
        except Exception:
            await query.message.delete()
        return

    # Claim daily via button
    if payload == "claim_daily":
        rec = ensure_user_record(data, uid)
        today_iso = _today_iso()
        last_daily_s = rec.get("last_daily", "")

        if last_daily_s == today_iso:
            # If already claimed, send a new message
            await query.answer() # Answer query to stop loading
            await query.message.reply_text("✅ You already claimed today's Daily Bonus.")
            return
        else:
            # Not claimed, so run the full logic (which edits the message)
            # We answer the query *inside* this function
            await handle_claim_daily_query(query, context)
            return
        
    # Redeem coupon button
    if payload == "redeem_coupon":
        context.user_data["flow"] = "redeem_code_entry"
        # Edit the message to ask for the code
        try:
            await query.message.edit_text("Please send the coupon code you want to redeem:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="show_earn")]]))
        except Exception:
            await query.message.reply_text("Please send the coupon code you want to redeem:", reply_markup=cancel_btn())
        return

    # Show referral link and details
    if payload == "show_ref_details":
        rec = ensure_user_record(data, uid)
        try:
            me = await context.bot.get_me()
            bot_user = me.username or "thisbot"
            ref_link = f"https://t.me/{bot_user}?start={uid}"
        except Exception:
            ref_link = f"/start {uid}"

        refs_list = rec.get("referrals", [])
        refs_count = len(refs_list)
        
        text = (
            f"🔗 *Your Referral Link*\n\n"
            f"Share this link to invite friends:\n`{ref_link}`\n\n"
            f"📣 *Your Referrals ({refs_count})*\n\n"
        )
        
        if not refs_list:
            text += "You haven't referred anyone yet."
        else:
            # Show the list of user IDs
            id_list_str = "\n".join([f"• User ID: `{id}`" for id in refs_list])
            text += id_list_str
            
        share_text = "👻 Hey! I'm using this awesome bot to hide my identity and earn rewards. Join using my link!"
        encoded_url = urllib.parse.quote(ref_link)
        encoded_text = urllib.parse.quote(share_text)
        share_url = f"https://t.me/share/url?url={encoded_url}&text={encoded_text}"
        
        kb = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("🔗 Share Link", url=share_url)],
                [InlineKeyboardButton("⬅️ Back", callback_data="show_earn")]
            ]
        )

        try:
            await query.message.edit_text(text, parse_mode="Markdown", reply_markup=kb, disable_web_page_preview=True)
        except Exception:
            await query.message.reply_text(text, parse_mode="Markdown", reply_markup=kb, disable_web_page_preview=True)
        return

    # Show Leaderboard
    if payload == "show_leaderboard":
        referrers, withdrawals = _generate_fake_leaderboard_data()
        
        text = "🏆 *Top Referrers*\n\n" 
        for i, ref in enumerate(referrers):
            text += f"{i+1}. {ref['name']} - {ref['count']} referrals\n"
            
        text += "\n\n💸 *Recent Withdrawals*\n\n" 
        for wd in withdrawals:
            text += f"• {wd['name']} withdrew ₹{wd['amount']}\n"
            
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Refresh", callback_data="show_leaderboard")],
            [InlineKeyboardButton("⬅️ Back", callback_data="show_earn")]
        ])
        
        try:
            await query.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
        except Exception:
            await query.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)
        return

    # Withdrawal panel
    if payload == "withdraw_panel":
        rec = ensure_user_record(data, uid)
        bal = int(rec.get("balance", 0))

        # Check for pending withdrawal first
        if rec.get("pending_withdrawal"):
            pw = rec.get("pending_withdrawal", {})
            pw_date = pw.get("date", "—")
            pw_time = pw.get("time", "—")
            text = f"💰 *Current Balance:* ₹{bal}\n\n⏳ You already have a pending withdrawal.\nRequested on: {pw_date} at {pw_time}"
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("⏳ Pending Withdrawal", callback_data="noop"), # No action
                                        InlineKeyboardButton("⬅️ Back", callback_data="show_earn")]])
            try:
                await query.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
            except Exception:
                await query.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)
            return

        # Check balance condition *before* showing stake details
        if bal < 2000:
            text = f"💰 *Total Balance:* ₹{bal}\n\n🔒 Earn ₹2000 to be able to request withdrawal. Keep earning!" # Updated message
            kb = InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("🔗 My Referral Link & Details", callback_data="show_ref_details"),
                     InlineKeyboardButton("⬅️ Back", callback_data="show_earn")],
                ]
            )
            try:
                await query.message.edit_text(text, parse_mode="Markdown", reply_markup=kb, disable_web_page_preview=True)
            except Exception:
                await query.message.reply_text(text, parse_mode="Markdown", reply_markup=kb, disable_web_page_preview=True)
            return

        # If balance >= 2000, show the stake/withdrawal info
        # Check if they ever unlocked it (internal flag)
        if rec.get("withdrawal_unlocked", False):
            stake_msg = (
                "🎯 *Withdrawal Requirements*\n\n"
                "Your *20-day Invite Stake* is active (or completed).\n"
                "Invite 1 person each calendar day (after 12:00 AM IST) for 20 consecutive days to complete the stake.\n\n"
                f"💰 *Current Balance:* ₹{bal}\n\n"
                "Press below to request withdrawal *only if* you've completed the 20-day stake."
            )
            kb = InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("💸 Request Withdrawal", callback_data="withdraw_confirm")],
                    [InlineKeyboardButton("⬅️ Back", callback_data="show_earn")],
                ]
            )
            try:
                await query.message.edit_text(stake_msg, parse_mode="Markdown", reply_markup=kb)
            except Exception:
                await query.message.reply_text(stake_msg, parse_mode="Markdown", reply_markup=kb)
            return
        else:
            # This case should ideally not happen if balance >= 2000, but as a fallback
            text = f"💰 *Total Balance:* ₹{bal}\n\n🔄 Initializing stake requirements..."
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="show_earn")]])
            try:
                await query.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
            except Exception:
                await query.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)
            return


    # Withdraw confirm (actual request attempt)
    if payload == "withdraw_confirm":
        rec = ensure_user_record(data, uid)
        bal = int(rec.get("balance", 0)) # Re-fetch current balance (should be >=2000 here)

        # Re-check conditions
        if bal < 2000:
            await query.answer("❌ You need at least ₹2000 balance to request withdrawal.", show_alert=True)
            return

        if not rec.get("stake_completed", False):
            await query.answer(f"❌ You must complete the 20-day Invite Stake first. Progress: {rec.get('stake_days_completed', 0)}/20", show_alert=True)
            return

        if rec.get("pending_withdrawal"):
            await query.answer("ℹ️ You already have a pending withdrawal request.", show_alert=True)
            return

        # --- THIS BLOCK IS EDITED ---
        amount = bal # Withdraw entire balance
        request_date = _today_date_str()
        request_time = _now_time_str()
        
        # 1. Set pending withdrawal
        rec["pending_withdrawal"] = {
            "amount": amount,
            "date": request_date,
            "time": request_time,
            "status": "requested"
        }
        
        # 2. Reset balance
        rec["balance"] = 0 
        
        # 3. Reset other stats
        rec["daily_streak"] = 0
        rec["withdrawal_unlocked"] = False # Re-lock until 2000 again
        rec["stake_active"] = False
        rec["stake_start_date"] = ""
        rec["stake_start_date_iso"] = ""
        rec["stake_days_completed"] = 0
        rec["stake_last_invite_date"] = ""
        rec["stake_last_invite_date_display"] = ""
        rec["stake_last_invite_time"] = ""
        rec["stake_completed"] = False
        
        # 4. Save all changes
        save_data(data)
        # --- END OF EDIT ---

        await query.message.edit_text(
            f"✅ Withdrawal request created for ₹{amount} on {request_date} at {request_time}. Owner will process it soon.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="show_earn")]]))

        owners = load_data().get("owners", [])
        for owner in owners:
            try:
                await context.bot.send_message(owner,
                                               f"💸 Withdrawal request:\nUser: `{uid}`\nAmount: ₹{amount}\nDate: {request_date}\nTime: {request_time}\nStake: Completed ✅",
                                               parse_mode="Markdown")
            except Exception:
                pass
        return

    # --- Owner Panel: Export Stats ---
    if payload == "owner_export_stats":
        if not is_owner(uid):
             await query.answer("❌ You are not authorized for this action.", show_alert=True)
             return
             
        await query.message.edit_text("🔄 Processing... generating user stats file. This may take a moment.")
        users = data.get("users", {})
        
        output = io.StringIO()
        writer = csv.writer(output)
        
        # CSV Header
        writer.writerow(["User ID", "Username", "Balance", "Referrals", "Daily Streak", "Stake Days", "Stake Completed"])
        
        # CSV Data
        for user_id_str, user_data in users.items():
            try:
                user_id = user_id_str
                username = user_data.get("username", "N/A")
                balance = user_data.get("balance", 0)
                referrals = len(user_data.get("referrals", []))
                streak = user_data.get("daily_streak", 0)
                stake_days = user_data.get("stake_days_completed", 0)
                stake_completed = "Yes" if user_data.get("stake_completed", False) else "No"
                writer.writerow([user_id, username, balance, referrals, streak, stake_days, stake_completed])
            except Exception:
                writer.writerow([user_id_str, "Error", 0, 0, 0, 0, "Error"])

        output.seek(0)
        
        file_data = output.getvalue().encode('utf-8')
        bio = io.BytesIO(file_data)
        bio.name = f"ghostcover_user_stats_{_today_iso()}.csv"
        
        try:
            await context.bot.send_document(
                chat_id=uid,
                document=bio,
                caption=f"✅ Here are the bot stats for {len(users)} users.\nDate: {_today_date_str()} {_now_time_str()}"
            )
            # Go back to owner panel
            await query.message.edit_text("🔧 *Owner Panel*\n\nChoose an option:", parse_mode="Markdown", reply_markup=owner_panel_kb())
        except Exception as e:
            await query.message.edit_text(f"Error sending file: {e}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="force_back")]]))
        return
        
    # --- Owner Panel Callbacks ---
    if not is_owner(uid):
        await query.answer("❌ You are not authorized for this action.", show_alert=True)
        return

    # Owner broadcast
    if payload == "owner_broadcast":
        context.user_data["flow"] = "broadcast_text"
        await query.message.edit_text("📢 Send the text to broadcast:", 
                                      reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="force_back")]]))
        return
        
    # Owner generate coupon
    if payload == "owner_coupon":
        context.user_data["flow"] = "coupon_amount"
        await query.message.edit_text("🎁 Send the amount (e.g., 500) for the new coupon:",
                                      reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="force_back")]]))
        return

    # Back to main owner panel
    if payload == "force_back": # Used by multiple sub-panels
        # Clear any potential modification target
        context.user_data.pop('target_user_id', None) 
        context.user_data.pop('flow', None) 
        await query.message.edit_text("🔧 *Owner Panel*\n\nChoose an option:", parse_mode="Markdown", reply_markup=owner_panel_kb())
        return
        
    # Show Owner Command List
    if payload == "owner_cmd_list":
        await query.message.edit_text(
            OWNER_COMMAND_LIST,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="force_back")]])
        )
        return

    # --- Owner Panel: Force Join ---
    if payload == "owner_force":
        force = data.get("force", {})
        status = "✅ Enabled" if force.get("enabled", False) else "❌ Disabled"
        count = len(force.get("channels", []))
        text = f"🔒 *Force Join Settings*\n\nStatus: {status}\nChannels: {count}\n\nChoose an option:"
        await query.message.edit_text(text, parse_mode="Markdown", reply_markup=force_setting_kb(force))
        return

    if payload == "force_toggle":
        force = data.setdefault("force", DEFAULT_DATA["force"])
        force["enabled"] = not force.get("enabled", False)
        save_data(data)
        
        status = "✅ Enabled" if force.get("enabled", False) else "❌ Disabled"
        count = len(force.get("channels", []))
        text = f"🔒 *Force Join Settings*\n\nStatus: {status}\nChannels: {count}\n\nChoose an option:"
        await query.message.edit_text(text, parse_mode="Markdown", reply_markup=force_setting_kb(force))
        return

    if payload == "force_add":
        context.user_data["flow"] = "force_add_channel"
        await query.message.edit_text(
            "➕ *Add Channel*\n\nSend the channel username (e.g., @username) or invite link (e.g., https://t.me/joinchat/...).",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="owner_force")]])
        )
        return

    if payload == "force_list":
        channels = data.get("force", {}).get("channels", [])
        if not channels:
            text = "📜 *Channel List*\n\nNo channels configured."
        else:
            text = "📜 *Channel List*\n\n"
            for i, ch in enumerate(channels):
                text += f"{i+1}. `{ch}`\n"
        
        await query.message.edit_text(
            text, 
            parse_mode="Markdown", 
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="owner_force")]])
        )
        return

    if payload == "force_remove":
        channels = data.get("force", {}).get("channels", [])
        if not channels:
            await query.answer("🗑️ No channels to remove.", show_alert=True)
            return
        
        buttons = []
        for i, ch in enumerate(channels):
            ch_str = str(ch)
            if len(ch_str) > 20:
                ch_str = ch_str[:20] + "..."
            buttons.append([InlineKeyboardButton(f"❌ {ch_str}", callback_data=f"force_del_idx_{i}")])
        buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="owner_force")])
        
        await query.message.edit_text("🗑️ *Remove Channel*\n\nSelect a channel to remove:", reply_markup=InlineKeyboardMarkup(buttons))
        return

    if payload.startswith("force_del_idx_"):
        try:
            idx = int(payload.split("_")[-1])
            channels = data.get("force", {}).get("channels", [])
            if 0 <= idx < len(channels):
                removed = channels.pop(idx)
                save_data(data)
                await query.answer(f"✅ Removed: {removed}", show_alert=True)
            else:
                await query.answer("Error: Invalid index.", show_alert=True)
        except Exception:
            await query.answer("Error processing removal.", show_alert=True)
        
        # Refresh the force panel
        force = data.get("force", {})
        status = "✅ Enabled" if force.get("enabled", False) else "❌ Disabled"
        count = len(force.get("channels", []))
        text = f"🔒 *Force Join Settings*\n\nStatus: {status}\nChannels: {count}\n\nChoose an option:"
        await query.message.edit_text(text, parse_mode="Markdown", reply_markup=force_setting_kb(force))
        return

    # --- Owner Panel: Manage Owner ---
    if payload == "owner_manage":
        kb = [
            [InlineKeyboardButton("➕ Add Owner", callback_data="owner_add")],
            [InlineKeyboardButton("🗑️ Remove Owner", callback_data="owner_remove")],
            [InlineKeyboardButton("📜 List Owners", callback_data="owner_list")],
            [InlineKeyboardButton("⬅️ Back", callback_data="force_back")] # 'force_back' goes to owner panel
        ]
        await query.message.edit_text("🧑‍💼 *Manage Owners*\n\nChoose an option:", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
        return
        
    if payload == "owner_add":
        context.user_data["flow"] = "owner_add_id"
        await query.message.edit_text(
            "➕ *Add Owner*\n\nSend the User ID of the new owner.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="owner_manage")]])
        )
        return

    if payload == "owner_list":
        owners = data.get("owners", [])
        text = "📜 *Owner List*\n\n"
        for owner_id in owners:
            label = ""
            if owner_id == OWNER_ID:
                label = " (Default)"
            if owner_id == uid:
                label += " (You)"
            text += f"• `{owner_id}`{label}\n"
        
        await query.message.edit_text(
            text, 
            parse_mode="Markdown", 
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="owner_manage")]])
        )
        return

    if payload == "owner_remove":
        owners = data.get("owners", [])
        buttons = []
        for owner_id in owners:
            if owner_id == OWNER_ID: # Can't remove the default owner
                buttons.append([InlineKeyboardButton(f"👑 {owner_id} (Default)", callback_data="noop")])
            elif owner_id == uid: # Can't remove yourself
                buttons.append([InlineKeyboardButton(f"🧑‍💼 {owner_id} (You)", callback_data="noop")])
            else:
                buttons.append([InlineKeyboardButton(f"❌ {owner_id}", callback_data=f"owner_del_id_{owner_id}")])
        buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="owner_manage")])
        
        await query.message.edit_text("🗑️ *Remove Owner*\n\nSelect an owner to remove:", reply_markup=InlineKeyboardMarkup(buttons))
        return

    if payload.startswith("owner_del_id_"):
        try:
            owner_to_remove = int(payload.split("_")[-1])
            owners = data.get("owners", [])
            
            if owner_to_remove in owners:
                if owner_to_remove == OWNER_ID:
                    await query.answer("Cannot remove the default owner.", show_alert=True)
                elif owner_to_remove == uid:
                    await query.answer("You cannot remove yourself.", show_alert=True)
                else:
                    owners.remove(owner_to_remove)
                    save_data(data)
                    await query.answer(f"✅ Owner removed: {owner_to_remove}", show_alert=True)
            else:
                await query.answer("Error: Owner not found.", show_alert=True)
        except Exception:
            await query.answer("Error processing removal.", show_alert=True)
        
        # Refresh the manage owner panel
        kb = [
            [InlineKeyboardButton("➕ Add Owner", callback_data="owner_add")],
            [InlineKeyboardButton("🗑️ Remove Owner", callback_data="owner_remove")],
            [InlineKeyboardButton("📜 List Owners", callback_data="owner_list")],
            [InlineKeyboardButton("⬅️ Back", callback_data="force_back")] 
        ]
        await query.message.edit_text("🧑‍💼 *Manage Owners*\n\nChoose an option:", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
        return

    # Owner Panel: View Withdrawals
    if payload == "owner_view_withdrawals":
        pending_requests = []
        users = data.get("users", {})
        for user_id_str, user_data in users.items():
            if user_data.get("pending_withdrawal"):
                pending_requests.append({"id": user_id_str, "data": user_data["pending_withdrawal"]})

        if not pending_requests:
            text = "⏳ *Pending Withdrawals*\n\nNo pending requests found."
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="force_back")]])
        else:
            text = "⏳ *Pending Withdrawals*\n\n"
            buttons = []
            # Sort requests by date/time if possible (best effort)
            try:
                pending_requests.sort(key=lambda x: (x['data'].get('date',''), x['data'].get('time','')))
            except: pass

            for req in pending_requests:
                user_id = req["id"]
                wd_data = req["data"]
                text += f"• User: `{user_id}`\n  Amount: ₹{wd_data.get('amount', '?')}\n  Date: {wd_data.get('date', '-')}\n  Time: {wd_data.get('time', '-')}\n\n"
                buttons.append([InlineKeyboardButton(f"✅ Mark Processed ({user_id})", callback_data=f"owner_process_wd_{user_id}")])
            
            buttons.append([InlineKeyboardButton("🔄 Refresh", callback_data="owner_view_withdrawals")])
            buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="force_back")])
            kb = InlineKeyboardMarkup(buttons)
            
        try:
            await query.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
        except Exception as e:
            print(f"Error editing withdrawal list: {e}") # Debugging
            await query.message.reply_text("Could not display list. Please try again.")
        return

    # Owner Panel: Process Withdrawal
    if payload.startswith("owner_process_wd_"):
        try:
            user_id_to_process = int(payload.split("_")[-1])
            user_id_str = str(user_id_to_process)
            users = data.get("users", {})
            
            if user_id_str in users and users[user_id_str].get("pending_withdrawal"):
                amount = users[user_id_str]["pending_withdrawal"].get('amount', 0)
                users[user_id_str]["pending_withdrawal"] = None # Remove pending status
                save_data(data)
                await query.answer(f"✅ Marked as processed for {user_id_str}.", show_alert=True)
                
                # Notify the user (best effort)
                try:
                    await context.bot.send_message(user_id_to_process, f"🎉 Your withdrawal request for ₹{amount} has been processed!")
                except Exception:
                    await query.message.reply_text(f"⚠️ User {user_id_str} might have blocked the bot. Could not notify them.")
                    
                # Refresh the withdrawal list for the owner by resending the command
                new_update_dict = query.to_dict()
                new_update_dict['data'] = 'owner_view_withdrawals'
                new_query = CallbackQuery.de_json(new_update_dict, context.bot)
                new_update = Update(update.update_id + 1, callback_query=new_query) 
                await callback_handler(new_update, context) # Call recursively

            else:
                await query.answer("❌ Request not found or already processed.", show_alert=True)
                
        except Exception as e:
            print(f"Error processing withdrawal: {e}") # Debugging
            await query.answer("❌ Error processing request.", show_alert=True)
        return

    # Owner Panel: Modify User (Entry Point)
    if payload == "owner_modify_user":
        context.user_data["flow"] = "owner_modify_user_id"
        await query.message.edit_text(
            "⚙️ *Modify User*\n\nPlease send the User ID you want to modify.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="force_back")]])
        )
        return

    # Owner Panel: Modify User Menu (after ID received)
    if payload == "owner_modify_menu":
        target_user_id = context.user_data.get("target_user_id")
        if not target_user_id:
            await query.message.edit_text("Error: Target user ID not found. Please start again.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="force_back")]]))
            return

        kb = [
            [InlineKeyboardButton("💰 Modify Balance", callback_data="owner_modify_balance_prompt")],
            [InlineKeyboardButton("🏁 Modify Stake Days", callback_data="owner_modify_stake_prompt")],
            [InlineKeyboardButton("ℹ️ Show User Info", callback_data="owner_show_user_info")],
            [InlineKeyboardButton("⬅️ Back (Owner Panel)", callback_data="force_back")]
        ]
        await query.message.edit_text(f"⚙️ Modifying User ID: `{target_user_id}`\n\nChoose an action:", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
        return

    # Owner Panel: Ask for Balance Command
    if payload == "owner_modify_balance_prompt":
        target_user_id = context.user_data.get("target_user_id")
        if not target_user_id:
            await query.message.edit_text("Error: Target user ID not found.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="force_back")]]))
            return
        context.user_data["flow"] = "owner_modify_balance_amount"
        await query.message.edit_text(
            f"💰 *Modify Balance for {target_user_id}*\n\nSend the new balance command:\n"
            "• `+Amount` (e.g., `+500`)\n"
            "• `-Amount` (e.g., `-100`)\n"
            "• `=Amount` (e.g., `=2000`)",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="owner_modify_menu")]])
        )
        return

    # Owner Panel: Ask for Stake Days
    if payload == "owner_modify_stake_prompt":
        target_user_id = context.user_data.get("target_user_id")
        if not target_user_id:
            await query.message.edit_text("Error: Target user ID not found.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="force_back")]]))
            return
        context.user_data["flow"] = "owner_modify_stake_days"
        await query.message.edit_text(
            f"🏁 *Modify Stake Days for {target_user_id}*\n\nSend the number of completed stake days (0-20).",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="owner_modify_menu")]])
        )
        return
        
    # Owner Panel: Show User Info
    if payload == "owner_show_user_info":
        target_user_id = context.user_data.get("target_user_id")
        if not target_user_id:
            await query.message.edit_text("Error: Target user ID not found.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="force_back")]]))
            return
            
        target_rec = get_user_record(data, target_user_id)
        if not target_rec:
            await query.message.edit_text("Error: User record not found.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="owner_modify_menu")]]))
            return
            
        bal = target_rec.get("balance", 0)
        refs = len(target_rec.get("referrals", []))
        streak = target_rec.get("daily_streak", 0)
        last_daily = target_rec.get('last_daily_display', 'Never')
        last_daily_t = target_rec.get('last_daily_time', '—')
        stake_active = target_rec.get('stake_active', False)
        stake_days = target_rec.get('stake_days_completed', 0)
        stake_start = target_rec.get('stake_start_date', '—')
        stake_completed = target_rec.get('stake_completed', False)
        
        status_text = (
            f"ℹ️ *User Info for {target_user_id}*\n\n"
            f"💰 Balance: ₹{bal}\n"
            f"📣 Referrals: {refs}\n"
            f"🔥 Daily Streak: {streak}\n"
            f"📅 Last Daily: {last_daily} at {last_daily_t}\n\n"
            f"--- Stake Info ---\n"
            f"🏁 Completed: {'Yes' if stake_completed else 'No'}\n"
            f"🟢 Active: {'Yes' if stake_active else 'No'}\n"
            f"🗓️ Days Done: {stake_days}/20\n"
            f"⏳ Started On: {stake_start}\n"
        )
        await query.message.edit_text(
            status_text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="owner_modify_menu")]])
            )
        return


# ---------------- Text flow handler ----------------
async def flow_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles all text-based "flows" (like broadcast, coupon entry).
    Must be registered BEFORE the generic echo_message handler.
    """
    uid = update.effective_user.id
    flow = context.user_data.get("flow")

    if not flow:
        # No flow, pass to next handler (echo_message)
        return

    # A flow is active. This handler MUST process it and return.
    data = load_data()
    text = update.message.text.strip()
    
    # We remove the old reply keyboard
    processing_msg = await update.message.reply_text("Processing...", reply_markup=ReplyKeyboardRemove())
    try:
        await processing_msg.delete()
    except Exception:
        pass


    if text == "❌ Cancel":
        context.user_data.clear()
        await update.message.reply_text("❌ Cancelled.", reply_markup=ReplyKeyboardRemove())
        await start_cmd(update, context)
        return

    # --- Owner Flows ---
    if is_owner(uid):
        if flow == "broadcast_text":
            subs = data.get("subscribers", [])
            sent = failed = 0
            msg_to_send = update.message.text # Get raw text to preserve formatting
            await update.message.reply_text(f"📢 Broadcasting to {len(subs)} users...")
            for u in subs:
                try:
                    await context.bot.send_message(u, msg_to_send)
                    sent += 1
                except Exception:
                    failed += 1
                await asyncio.sleep(0.1)
            
            await update.message.reply_text(f"✅ Broadcast done. Sent: {sent}, Failed: {failed}",
                                            reply_markup=ReplyKeyboardRemove())
            context.user_data.clear()
            await owner_cmd(update, context) # Show owner panel again
            return

        if flow == "coupon_amount":
            try:
                amount = int(text)
                if amount <= 0:
                    raise ValueError("Amount must be positive")

                new_code = _generate_coupon_code(data)
                data.setdefault("coupons", {})[new_code] = {
                    "amount": amount,
                    "status": "active",
                    "redeemed_by": None,
                    "redeemed_at": "",
                    "created_by": uid,
                    "created_at": f"{_today_date_str()} {_now_time_str()}"
                }
                save_data(data)
                await update.message.reply_text(
                    f"✅ Coupon generated:\n\n`{new_code}`\n\nAmount: ₹{amount}",
                    parse_mode="Markdown", reply_markup=ReplyKeyboardRemove())
            except ValueError:
                await update.message.reply_text("Invalid amount. Please send a positive number (e.g., 500).")
            
            context.user_data.clear()
            await owner_cmd(update, context)
            return
            
        if flow == "force_add_channel":
            if not text:
                await update.message.reply_text("Invalid input. Please send a username or link.")
            else:
                force = data.setdefault("force", DEFAULT_DATA["force"])
                channels = force.setdefault("channels", [])
                
                channels.append(text)
                save_data(data)
                await update.message.reply_text(f"✅ Channel added: {text}")
            
            context.user_data.clear()
            await owner_cmd(update, context) 
            return

        if flow == "owner_add_id":
            try:
                new_owner_id = int(text)
                owners = data.setdefault("owners", [OWNER_ID])
                if new_owner_id in owners:
                    await update.message.reply_text("That user is already an owner.")
                else:
                    owners.append(new_owner_id)
                    save_data(data)
                    await update.message.reply_text(f"✅ Owner added: {new_owner_id}")
            except ValueError:
                await update.message.reply_text("Invalid User ID. Please send numbers only.")
            
            context.user_data.clear()
            await owner_cmd(update, context)
            return
            
        if flow == "owner_modify_user_id":
            try:
                target_user_id = int(text)
                target_rec = get_user_record(data, target_user_id)
                if not target_rec:
                    await update.message.reply_text(f"❌ User ID `{target_user_id}` not found in database.", parse_mode="Markdown")
                    context.user_data.clear()
                    await owner_cmd(update, context)
                else:
                    context.user_data['target_user_id'] = target_user_id
                    context.user_data['flow'] = None # Clear flow to allow button press
                    
                    kb = [
                        [InlineKeyboardButton("💰 Modify Balance", callback_data="owner_modify_balance_prompt")],
                        [InlineKeyboardButton("🏁 Modify Stake Days", callback_data="owner_modify_stake_prompt")],
                        [InlineKeyboardButton("ℹ️ Show User Info", callback_data="owner_show_user_info")],
                        [InlineKeyboardButton("⬅️ Back (Owner Panel)", callback_data="force_back")]
                    ]
                    # Need to use reply_text here as edit_text won't work after processing_msg deletion
                    await update.message.reply_text(f"⚙️ Modifying User ID: `{target_user_id}`\n\nChoose an action:", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

            except ValueError:
                await update.message.reply_text("Invalid User ID. Please send numbers only.")
                context.user_data.clear()
                await owner_cmd(update, context)
            return

        if flow == "owner_modify_balance_amount":
            target_user_id = context.user_data.get("target_user_id")
            if not target_user_id:
                await update.message.reply_text("Error: Target user ID lost. Please start again.")
                context.user_data.clear()
                await owner_cmd(update, context)
                return
            
            target_rec = ensure_user_record(data, target_user_id)
            current_balance = int(target_rec.get("balance", 0))
            new_balance = current_balance # Default if command is invalid
            
            try:
                if text.startswith('+'):
                    amount = int(text[1:])
                    new_balance = current_balance + amount
                elif text.startswith('-'):
                    amount = int(text[1:])
                    new_balance = max(0, current_balance - amount) # Ensure non-negative
                elif text.startswith('='):
                    amount = int(text[1:])
                    new_balance = max(0, amount) # Ensure non-negative
                else:
                    raise ValueError("Invalid format")

                target_rec['balance'] = new_balance
                #save_data(data) # Save combined below
                
                # Check if stake needs unlocking due to manual balance increase
                stake_unlocked_msg = ""
                if current_balance < 2000 <= new_balance and not target_rec.get("withdrawal_unlocked"):
                    target_rec["withdrawal_unlocked"] = True
                    # Set stake details if not already set
                    if not target_rec.get("stake_start_date"):
                        iso_today = _today_iso()
                        target_rec["stake_start_date_iso"] = iso_today
                        target_rec["stake_start_date"] = _today_date_str()
                        target_rec["stake_active"] = True
                        target_rec["stake_days_completed"] = 0
                    stake_unlocked_msg = f"\nℹ️ Stake unlocked for user `{target_user_id}`."

                save_data(data) # Save all changes
                await update.message.reply_text(f"✅ User `{target_user_id}` balance updated to ₹{new_balance}.{stake_unlocked_msg}", parse_mode="Markdown")

            except ValueError:
                await update.message.reply_text("Invalid command format. Use `+Amount`, `-Amount`, or `=Amount`.")

            context.user_data['flow'] = None # Clear flow
            # Go back to modify menu by simulating callback
            # Create a pseudo-update to trigger the callback handler
            # We use the message update as the base
            pseudo_callback_data = 'owner_modify_menu'
            await update.message.reply_text(f"Returning to menu for user `{target_user_id}`...", reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💰 Modify Balance", callback_data="owner_modify_balance_prompt")],
                [InlineKeyboardButton("🏁 Modify Stake Days", callback_data="owner_modify_stake_prompt")],
                [InlineKeyboardButton("ℹ️ Show User Info", callback_data="owner_show_user_info")],
                [InlineKeyboardButton("⬅️ Back (Owner Panel)", callback_data="force_back")]
            ]))
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=update.message.message_id + 1) # Delete processing msg

            return

        if flow == "owner_modify_stake_days":
            target_user_id = context.user_data.get("target_user_id")
            if not target_user_id:
                await update.message.reply_text("Error: Target user ID lost. Please start again.")
                context.user_data.clear()
                await owner_cmd(update, context)
                return

            target_rec = ensure_user_record(data, target_user_id)
            stake_completed_msg = ""
            
            try:
                days = int(text)
                if 0 <= days <= 20:
                    target_rec['stake_days_completed'] = days
                    if days == 20:
                        target_rec['stake_completed'] = True
                        target_rec['stake_active'] = False # Mark inactive when completed manually
                        stake_completed_msg = f"\nℹ️ Stake marked as completed for user `{target_user_id}`."
                    else:
                        target_rec['stake_completed'] = False
                        # We don't change 'stake_active' here, it depends on invites
                        
                    save_data(data)
                    await update.message.reply_text(f"✅ User `{target_user_id}` stake days set to {days}/20.{stake_completed_msg}", parse_mode="Markdown")

                else:
                    await update.message.reply_text("Invalid number. Please enter a value between 0 and 20.")
                    
            except ValueError:
                await update.message.reply_text("Invalid input. Please send a number between 0 and 20.")
            
            context.user_data['flow'] = None # Clear flow
            # Go back to modify menu by simulating callback
            await update.message.reply_text(f"Returning to menu for user `{target_user_id}`...", reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💰 Modify Balance", callback_data="owner_modify_balance_prompt")],
                [InlineKeyboardButton("🏁 Modify Stake Days", callback_data="owner_modify_stake_prompt")],
                [InlineKeyboardButton("ℹ️ Show User Info", callback_data="owner_show_user_info")],
                [InlineKeyboardButton("⬅️ Back (Owner Panel)", callback_data="force_back")]
            ]))
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=update.message.message_id + 1) # Delete processing msg
            return
        # --- End of Modify User Flows ---


    # --- User Flows ---
    if flow == "redeem_code_entry":
        code = text.upper()
        coupons = data.setdefault("coupons", {})
        coupon = coupons.get(code)

        if not coupon or coupon.get("status") != "active":
            await update.message.reply_text("❌ Invalid coupon code or it has already been redeemed.",
                                            reply_markup=ReplyKeyboardRemove())
            context.user_data.clear()
            await start_cmd(update, context)
            return

        amount = int(coupon["amount"])
        coupon["status"] = "redeemed"
        coupon["redeemed_by"] = uid
        coupon["redeemed_at"] = f"{_today_date_str()} {_now_time_str()}"

        award_balance(data, uid, amount)
        rec = ensure_user_record(data, uid)

        await update.message.reply_text(
            f"✅ Coupon redeemed! ₹{amount} has been added.\nNew balance: ₹{rec.get('balance')}",
            reply_markup=ReplyKeyboardRemove())

        for owner in data.get("owners", []):
            try:
                await context.bot.send_message(owner,
                                               f"🎁 Coupon redeemed:\nCode: `{code}` (₹{amount})\nUser: `{uid}`",
                                               parse_mode="Markdown")
            except Exception:
                pass

        context.user_data.clear()
        await start_cmd(update, context)
        return

    # Flow existed but wasn't handled
    await update.message.reply_text("Action cancelled or invalid.", reply_markup=ReplyKeyboardRemove())
    context.user_data.clear()


# ---------------- Ghost copier (echo) ----------------
async def echo_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # only private chats
    if update.effective_chat.type != "private":
        return

    # If user is in a text-based flow, don't echo media
    if context.user_data.get("flow"):
        if update.message and update.message.text:
            await update.message.reply_text("Please complete or cancel the current action.", reply_markup=cancel_btn())
        else:
            await update.message.reply_text("Please send text or '❌ Cancel' to complete the current action.",
                                            reply_markup=cancel_btn())
        return
        
    user = update.effective_user
    data = load_data()

    # Force-join checks for non-owners
    if not is_owner(user.id):
        force = data.get("force", {})
        if force.get("enabled", False) and force.get("channels"):
            missing, check_failed = await get_missing_channels(context, user.id)
            if missing:
                subs = data.setdefault("subscribers", [])
                if user.id in subs:
                    subs.remove(user.id)
                    save_data(data)
                await prompt_user_with_missing_channels(update, context, missing, check_failed)
                return

    # copy the incoming message back to the same chat (removes forward tag)
    try:
        await update.message.copy(chat_id=update.effective_chat.id)
    except Exception:
        pass


# ---------------- Run ----------------
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("owner", owner_cmd))
    app.add_handler(CommandHandler("daily", daily_cmd))
    app.add_handler(CommandHandler("stake_status", stake_status_cmd))

    # Callback handler
    app.add_handler(CallbackQueryHandler(callback_handler))

    # Text handler for flows (broadcast, redeem, etc.)
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, flow_text_handler), group=1)

    # Generic echo for all other messages (media, or text with no flow)
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND & filters.ChatType.PRIVATE, echo_message), group=2)

    print("🤖 GhostCoverBot running...")
    app.run_polling()


if __name__ == "__main__":
    main()