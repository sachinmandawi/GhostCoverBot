# ghostcoverbot_full_updated_fixed.py
# Ready-to-run GhostCoverBot (copy everything in private chats)
# Requirements: python-telegram-bot >= 20.x

import json
import os
import shutil
import traceback
import re
from datetime import datetime

from telegram import (
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
from telegram.ext.filters import BaseFilter

# ================ CONFIG =================
BOT_TOKEN = "8001331074:AAEQuKItN0fwOuuax0rsVVkbMlcJ05-5zKY"  # consider rotating token if production
OWNER_ID = 8070535163
DATA_FILE = "data.json"
LAST_BACKUP_FILE = "last_backup.json"
# =========================================

WELCOME_TEXT = (
    "👻 *Hey there! I’m GhostCoverBot*\n\n"
    "🔹 I hide your identity like a pro.\n"
    "🔹 Just send me any message — text, photo, or video.\n"
    "🔹 I’ll instantly send it back *without a forward tag!*\n\n"
    "📤 Forward it anywhere — people will think *I sent it!*"
)

DEFAULT_DATA = {
    "subscribers": [],
    "owners": [OWNER_ID],
    "force": {
        # Force-join enabled by default and preconfigured channel
        "enabled": True,
        "channels": [
            {"chat_id": "@QorvraGroup", "invite": None, "join_btn_text": "📢 Main Group"}
        ],
        "check_btn_text": "✅ Verify",
    },
    "known_chats": [],
    # Auto-backup enabled by default with 1 minute interval as requested
    "auto_backup": {
        "enabled": True,
        "interval_minutes": 1,
    },
    "sent_backup_messages": {},
    "stats": {},
}

# ---------- Local DB Helpers ----------
def _check_and_reset_daily_stats(data):
    today = datetime.now().strftime("%Y-%m-%d")
    stats = data.setdefault("stats", {})
    if today not in stats:
        stats[today] = {"new_users": 0}
    return data


def _ensure_data_keys(data):
    for key, value in DEFAULT_DATA.items():
        data.setdefault(key, value)
    if "force" in data:
        for k, v in DEFAULT_DATA["force"].items():
            data["force"].setdefault(k, v)
    if "auto_backup" not in data:
        data["auto_backup"] = DEFAULT_DATA["auto_backup"].copy()
    if "sent_backup_messages" not in data:
        data["sent_backup_messages"] = {}
    if "stats" not in data:
        data["stats"] = {}
    return data


def load_data_from_local():
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_DATA, f, indent=2)
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except Exception:
            data = DEFAULT_DATA.copy()
    return _ensure_data_keys(data)


def save_data_to_local(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_data():
    return load_data_from_local()


def save_data(data):
    save_data_to_local(data)


def is_owner(uid: int) -> bool:
    data = load_data()
    return uid in data.get("owners", [])


class IsOwnerFilter(BaseFilter):
    def filter(self, message):
        if not message or not getattr(message, "from_user", None):
            return False
        return is_owner(message.from_user.id)


is_owner_filter = IsOwnerFilter()

# ---------- Merge helpers ----------
def merge_data(existing: dict, new: dict):
    merged = dict(existing)
    summary = {"new_bot_users": 0, "owners_added": 0, "force_channels_added": 0, "chats_added": 0}

    def to_int_list(items):
        if not isinstance(items, list):
            return []
        result = []
        for item in items:
            try:
                result.append(int(item))
            except Exception:
                # keep non-int IDs as-is? currently skip; you can change behavior if needed
                pass
        return result

    e_owners = set(to_int_list(existing.get("owners", [])))
    n_owners = set(to_int_list(new.get("owners", [])))
    combined_owners = list(e_owners.union(n_owners))
    summary["owners_added"] = max(0, len(combined_owners) - len(e_owners))
    merged["owners"] = combined_owners
    
    e_subs = set(to_int_list(existing.get("subscribers", [])))
    n_subs = set(to_int_list(new.get("subscribers", [])))
    combined_subs = list(e_subs.union(n_subs))
    summary["new_bot_users"] = max(0, len(combined_subs) - len(e_subs))
    merged["subscribers"] = combined_subs
        
    e_chats = existing.get("known_chats", []) or []
    n_chats = new.get("known_chats", []) or []
    combined_chats = e_chats.copy()
    existing_ids = {c.get("chat_id") for c in e_chats}
    added_chats = 0
    for c in n_chats:
        if c.get("chat_id") not in existing_ids:
            combined_chats.append(c)
            existing_ids.add(c.get("chat_id"))
            added_chats += 1
    merged["known_chats"] = combined_chats
    summary["chats_added"] = added_chats

    e_force = existing.get("force", {}) or {}
    n_force = new.get("force", {}) or {}
    e_channels = e_force.get("channels", []) or []
    n_channels = n_force.get("channels", []) or []
    combined_channels = e_channels.copy()
    seen = {ch.get("chat_id") or ch.get("invite") for ch in e_channels}
    added_force = 0
    for ch in n_channels:
        key = ch.get("chat_id") or ch.get("invite")
        if key not in seen:
            combined_channels.append(ch)
            seen.add(key)
            added_force += 1
    merged_force = dict(e_force)
    merged_force["channels"] = combined_channels
    if n_force.get("check_btn_text"):
        merged_force["check_btn_text"] = n_force.get("check_btn_text")
    merged["force"] = merged_force
    summary["force_channels_added"] = added_force

    merged["auto_backup"] = existing.get("auto_backup", DEFAULT_DATA["auto_backup"]).copy()
    merged["sent_backup_messages"] = existing.get("sent_backup_messages", {})
    merged["stats"] = existing.get("stats", {})

    return merged, summary

# ---------- Utility functions ----------
def _normalize_channel_entry(raw):
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        text = raw.strip()
        if text.startswith("http"):
            return {"chat_id": None, "invite": text, "join_btn_text": None}
        else:
            return {"chat_id": text, "invite": None, "join_btn_text": None}
    return {}


def _derive_query_chat_from_entry(ch):
    chat_id = ch.get("chat_id")
    if chat_id:
        return chat_id
    invite = ch.get("invite")
    if invite and "t.me/" in invite:
        possible = invite.rstrip("/").split("/")[-1]
        if possible and not possible.lower().startswith(("joinchat", "+")):
            return f"@{possible}"
    return None


def build_join_keyboard_for_channels_list(ch_list, force_cfg):
    buttons = []
    for ch in ch_list:
        join_label = ch.get("join_btn_text") or "🔗 Join Channel"
        url = ch.get("invite")
        if not url and ch.get("chat_id", "") and str(ch.get("chat_id")).startswith("@"):
            url = f"https://t.me/{str(ch['chat_id']).lstrip('@')}"
        buttons.append(InlineKeyboardButton(join_label, url=url if url else "force_no_invite"))
    
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    check_label = force_cfg.get("check_btn_text") or "✅ Verify"
    rows.append([InlineKeyboardButton(check_label, callback_data="check_join")])
    return InlineKeyboardMarkup(rows)


async def get_missing_channels(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    force = load_data().get("force", {})
    raw_channels = force.get("channels", [])
    if not raw_channels:
        return [], False
    
    missing, check_failed = [], False
    for ch_raw in raw_channels:
        ch = _normalize_channel_entry(ch_raw)
        query_chat = _derive_query_chat_from_entry(ch)
        if query_chat:
            try:
                member = await context.bot.get_chat_member(chat_id=query_chat, user_id=user_id)
                if member.status in ("left", "kicked"):
                    missing.append(ch)
            except Exception:
                missing.append(ch)
                check_failed = True
        else:
            # If entry can't be resolved treat as missing so owner can fix it
            missing.append(ch)
    return missing, check_failed


async def prompt_user_with_missing_channels(update: Update, context: ContextTypes.DEFAULT_TYPE, missing_norm_list, check_failed=False):
    if not missing_norm_list:
        return
    text = "🔒 *Access Restricted*\n\nYou need to join the required channels. Tap the buttons, join, then press **Verify**."
    kb = build_join_keyboard_for_channels_list(missing_norm_list, load_data().get("force", {}))
    target = update.callback_query.message if update.callback_query else update.message
    await target.reply_text(text, parse_mode="Markdown", reply_markup=kb)

# ---------- Keyboards ----------
def owner_panel_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Broadcast", callback_data="owner_broadcast"), InlineKeyboardButton("🔒 Force Join", callback_data="owner_force")],
        [InlineKeyboardButton("🧑‍💼 Manage Owner", callback_data="owner_manage")],
        [InlineKeyboardButton("🗄️ Database", callback_data="owner_db"), InlineKeyboardButton("📊 Statistics", callback_data="owner_stats")],
        [InlineKeyboardButton("⬅️ Close", callback_data="owner_close")],
    ])


def db_panel_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 Import (overwrite)", callback_data="db_import"), InlineKeyboardButton("📤 Export", callback_data="db_export")],
        [InlineKeyboardButton("📥 Import & Merge", callback_data="db_import_merge")],
        [InlineKeyboardButton("🧹 Clear DB", callback_data="db_clear")],
        [InlineKeyboardButton("↩️ Undo Last Backup", callback_data="db_undo")],
        [InlineKeyboardButton("⚙️ Auto Backup", callback_data="db_autobackup")],
        [InlineKeyboardButton("⬅️ Back to Owner Panel", callback_data="db_back")],
    ])


def autobackup_kb(data):
    ab = data.get("auto_backup", {})
    status_text = "✅ On" if ab.get("enabled", False) else "❌ Off"
    interval = ab.get("interval_minutes", 1)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"Toggle ({status_text})", callback_data="db_backup_toggle")],
        [InlineKeyboardButton(f"Interval ({interval}m)", callback_data="db_backup_set_interval")],
        [InlineKeyboardButton("⬅️ Back", callback_data="db_back")],
    ])


def force_setting_kb(force: dict):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔁 Toggle Force-Join", callback_data="force_toggle"), InlineKeyboardButton("➕ Add Channel", callback_data="force_add")],
        [InlineKeyboardButton("🗑️ Remove Channel", callback_data="force_remove"), InlineKeyboardButton("📜 List Channel", callback_data="force_list")],
        [InlineKeyboardButton("⬅️ Back", callback_data="force_back")],
    ])


def cancel_btn():
    return ReplyKeyboardMarkup([["❌ Cancel"]], resize_keyboard=True, one_time_keyboard=True)

# ---------- Auto-backup helpers ----------
def parse_interval_to_minutes(text: str) -> int:
    s = text.strip().lower()
    if s.isdigit():
        return int(s)
    total = 0
    # safer parsing: find hours and minutes with regex
    hours_match = re.search(r"(\d+)\s*h", s)
    mins_match = re.search(r"(\d+)\s*m", s)
    if hours_match:
        try:
            hours = int(hours_match.group(1))
        except Exception:
            hours = 0
    else:
        hours = 0
    if mins_match:
        try:
            minutes = int(mins_match.group(1))
        except Exception:
            minutes = 0
    else:
        minutes = 0
    total = hours * 60 + minutes
    if total <= 0:
        raise ValueError("Interval must be positive.")
    return total


async def perform_and_send_backup(context: ContextTypes.DEFAULT_TYPE):
    try:
        data = load_data()
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        fname = f"auto_backup_{timestamp}.json"
        
        with open(fname, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
        shutil.copyfile(fname, LAST_BACKUP_FILE)
        
        owners = data.get("owners", []) or [OWNER_ID]
        backup_log = data.setdefault("sent_backup_messages", {})
        
        for o in owners:
            try:
                sent_message = await context.bot.send_document(chat_id=o, document=open(fname, "rb"), caption=f"📦 Auto-backup: {timestamp}")
                owner_log = backup_log.setdefault(str(o), [])
                owner_log.append(sent_message.message_id)
                if len(owner_log) > 5:
                    await context.bot.delete_message(chat_id=o, message_id=owner_log.pop(0))
            except Exception as send_err:
                print(f"Failed to send backup to owner {o}: {send_err}")
        
        save_data(data)
        os.remove(fname)
    except Exception as e:
        print(f"Auto-backup failed: {e}")


def schedule_auto_backup_job(application: Application, interval_minutes: int):
    # remove existing
    for j in application.job_queue.get_jobs_by_name("auto_backup"):
        j.schedule_removal()
    if interval_minutes > 0:
        application.job_queue.run_repeating(perform_and_send_backup, interval=interval_minutes * 60, first=10, name="auto_backup")

# ---------- Commands ----------
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    data = load_data()

    if is_owner(user.id):
        context.user_data.clear()
        await update.message.reply_text("✅ *Normal Mode Activated*\nYour messages will now be copy-forwarded.", parse_mode="Markdown")
    else:
        force = data.get("force", {})
        # Only perform force-check if it's enabled AND there are configured channels
        if force.get("enabled") and force.get("channels"):
            missing, check_failed = await get_missing_channels(context, user.id)
            if missing:
                if user.id in data.get("subscribers", []):
                    data["subscribers"].remove(user.id)
                    save_data(data)
                await prompt_user_with_missing_channels(update, context, missing, check_failed)
                return

    if user.id not in data.get("subscribers", []):
        data["subscribers"].append(user.id)
        data = _check_and_reset_daily_stats(data)
        today = datetime.now().strftime("%Y-%m-%d")
        data["stats"][today]["new_users"] += 1
        save_data(data)

    await update.message.reply_text(WELCOME_TEXT, parse_mode="Markdown")


async def owner_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("❌ Only owners can access this panel.")
        return
    
    context.user_data['admin_mode'] = True
    await update.message.reply_text(
        "✅ *Owner Mode Activated*\n\nCopy-forward is now OFF for you. Choose an option:",
        parse_mode="Markdown", reply_markup=owner_panel_kb()
    )

# ---------- Callback Handler ----------
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    payload = query.data
    data = load_data()

    if not is_owner(uid) and any(payload.startswith(p) for p in ["owner_", "db_", "mgr_", "force_"]):
        return await query.message.reply_text("❌ Only owners can use this function.")

    if payload == "owner_close":
        context.user_data.clear()
        return await query.message.edit_text("✅ *Normal Mode Activated*\nCopy-forward is now ON for you.", parse_mode="Markdown")

    if payload in ["mgr_back", "force_back", "db_back"]:
        context.user_data['admin_mode'] = True
        return await query.message.edit_text("✅ *Owner Mode Activated*\nChoose an option:", parse_mode="Markdown", reply_markup=owner_panel_kb())

    if payload == "owner_stats":
        data = _check_and_reset_daily_stats(data)
        today_str = datetime.now().strftime("%Y-%m-%d")
        today_stats = data.get("stats", {}).get(today_str, {"new_users": 0})
        stats_msg = (
            f"📊 *Bot Statistics*\n\n"
            f"👤 Total Users: *{len(data.get('subscribers', []))}*\n"
            f"📈 New Users Today: *{today_stats.get('new_users', 0)}*"
        )
        return await query.message.edit_text(stats_msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="db_back")]]))

    if payload == "owner_db":
        return await query.message.edit_text("🗄️ *Database Management*", parse_mode="Markdown", reply_markup=db_panel_kb())
    
    if payload == "db_export":
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        fname = f"backup_{timestamp}.json"
        with open(fname, "w", encoding="utf-8") as f: json.dump(load_data(), f, indent=4)
        await context.bot.send_document(chat_id=query.message.chat_id, document=open(fname, "rb"), caption="📄 Database export.")
        os.remove(fname)
        return

    if payload in ["db_import", "db_import_merge"]:
        context.user_data["flow"] = "db_import_file" if payload == "db_import" else "db_import_merge_file"
        prompt = "IMPORT (overwrite)" if payload == "db_import" else "MERGE"
        return await query.message.reply_text(f"📥 Please upload the `.json` file to {prompt}.", reply_markup=cancel_btn())
    
    if payload == "db_clear":
        kb = [[InlineKeyboardButton("✅ Confirm Clear", callback_data="db_confirm_clear")], [InlineKeyboardButton("❌ Cancel", callback_data="db_back")]]
        return await query.message.edit_text("⚠️ *Clear Database*\n\nThis will BACKUP then CLEAR all data. Are you sure?", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
    
    if payload == "db_confirm_clear":
        await query.message.edit_text("⏳ Clearing database...")
        current_data = load_data()
        shutil.copyfile(DATA_FILE, LAST_BACKUP_FILE)
        new_data = DEFAULT_DATA.copy()
        new_data["owners"] = current_data.get("owners", [OWNER_ID])
        save_data(new_data)
        return await query.message.edit_text("✅ Database cleared. Owners preserved. Use 'Undo' to restore.", reply_markup=db_panel_kb())
    
    if payload == "db_undo":
        if not os.path.exists(LAST_BACKUP_FILE):
            return await query.message.reply_text("ℹ️ No last backup found.", reply_markup=db_panel_kb())
        kb = [[InlineKeyboardButton("✅ Confirm Restore", callback_data="db_confirm_undo")], [InlineKeyboardButton("❌ Cancel", callback_data="db_back")]]
        return await query.message.edit_text("⚠️ *Restore Last Backup*\n\nOverwrite current DB with the last backup?", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

    if payload == "db_confirm_undo":
        try:
            shutil.copyfile(LAST_BACKUP_FILE, DATA_FILE)
            await query.message.edit_text("✅ Restored from last backup.", reply_markup=db_panel_kb())
        except Exception as e:
            await query.message.edit_text(f"❌ Restore failed: {e}", reply_markup=db_panel_kb())
        return

    if payload == "db_autobackup":
        return await query.message.edit_text("⚙️ *Auto Backup Settings*", parse_mode="Markdown", reply_markup=autobackup_kb(data))
    
    if payload == "db_backup_toggle":
        ab = data.setdefault("auto_backup", {})
        ab["enabled"] = not ab.get("enabled", False)
        save_data(data)
        if ab["enabled"]: schedule_auto_backup_job(context.application, ab.get("interval_minutes", 1))
        else: schedule_auto_backup_job(context.application, 0)
        return await query.message.edit_text("⚙️ *Auto Backup Settings*", parse_mode="Markdown", reply_markup=autobackup_kb(load_data()))

    if payload == "db_backup_set_interval":
        context.user_data["flow"] = "set_backup_interval"
        return await query.message.reply_text("⏱️ Send new interval (e.g., 30m, 2h, 1h30m)", reply_markup=cancel_btn())

    if payload == "owner_broadcast":
        context.user_data["flow"] = "broadcast_text"
        return await query.message.reply_text("📢 Send the message to broadcast (text, photo, file, etc.):", reply_markup=cancel_btn())

    if payload == "owner_manage":
        kb = [[InlineKeyboardButton("➕ Add", callback_data="mgr_add"), InlineKeyboardButton("📜 List", callback_data="mgr_list")],
              [InlineKeyboardButton("🗑️ Remove", callback_data="mgr_remove"), InlineKeyboardButton("⬅️ Back", callback_data="mgr_back")]]
        return await query.message.edit_text("🧑‍💼 *Manage Owner*", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

    if payload == "mgr_add":
        context.user_data["flow"] = "mgr_add"
        return await query.message.reply_text("➕ Send numeric user ID to add:", reply_markup=cancel_btn())
    if payload == "mgr_list":
        owners = "\n".join([f"• `{o}`" for o in data.get("owners", [])])
        return await query.message.reply_text(f"🧑‍💼 *Owners:*\n{owners}", parse_mode="Markdown")
    if payload == "mgr_remove":
        owners = data.get("owners", [])
        if len(owners) <= 1: return await query.message.reply_text("❌ At least one owner must remain.")
        kb = [[InlineKeyboardButton(f"Remove: {_normalize_channel_entry(ch).get('chat_id') or _normalize_channel_entry(ch).get('invite') or 'Invalid Entry'}", callback_data=f"force_rem_{i}")] for i, ch in enumerate(data.get("force", {}).get("channels", []))]
        kb = [[InlineKeyboardButton(f"Remove: {o}", callback_data=f"mgr_rem_{i}")] for i, o in enumerate(owners)]
        return await query.message.edit_text("Select an owner to remove:", reply_markup=InlineKeyboardMarkup(kb))
    
    if payload.startswith("mgr_rem_"):
        idx = int(payload.split("_")[-1])
        removed_id = data["owners"][idx]
        data["owners"].pop(idx)
        save_data(data)
        await query.message.edit_text(f"✅ Removed owner `{removed_id}`.", parse_mode="Markdown")
        
        try:
            await context.bot.send_message(
                chat_id=removed_id,
                text="ℹ️ You have been removed as an owner of this bot."
            )
        except Exception as e:
            print(f"[INFO] Could not notify removed owner {removed_id}: {e}")
        return

    if payload == "owner_force":
        status = "Enabled ✅" if data.get("force", {}).get("enabled") else "Disabled ❌"
        msg = f"🔒 *Force Join Setting*\n\nStatus: `{status}`"
        return await query.message.edit_text(msg, parse_mode="Markdown", reply_markup=force_setting_kb(data.get("force", {})))

    if payload == "force_toggle":
        force = data.setdefault("force", {})
        force["enabled"] = not force.get("enabled", False)
        save_data(data)
        status = "Enabled ✅" if force["enabled"] else "Disabled ❌"
        msg = f"🔒 *Force Join Setting*\n\nStatus: `{status}`"
        await query.message.edit_text(msg, parse_mode="Markdown", reply_markup=force_setting_kb(force))
        if force["enabled"] and not force.get("channels"):
            await query.message.reply_text("⚠️ Force-Join is on but no channels are set.", parse_mode="Markdown")
        return

    if payload == "force_add":
        context.user_data["flow"] = "force_add_step1"
        return await query.message.reply_text("➕ Send channel ID (`@channel` or `-100...`) or invite link.", reply_markup=cancel_btn())
        
    if payload == "force_remove":
        channels = data.get("force", {}).get("channels", [])
        if not channels: return await query.message.reply_text("ℹ️ No channels to remove.")
        kb = [[InlineKeyboardButton(f"Remove: {_normalize_channel_entry(ch).get('chat_id') or _normalize_channel_entry(ch).get('invite') or 'Invalid Entry'}", callback_data=f"force_rem_{i}")] for i, ch in enumerate(channels)]
        return await query.message.edit_text("Select channel to remove:", reply_markup=InlineKeyboardMarkup(kb))

    if payload.startswith("force_rem_"):
        idx = int(payload.split("_")[-1])
        data["force"]["channels"].pop(idx)
        save_data(data)
        return await query.message.edit_text(f"✅ Channel removed.", parse_mode="Markdown")

    if payload == "force_list":
        channels = data.get("force", {}).get("channels", [])
        if not channels: return await query.message.reply_text("ℹ️ No channels configured.")
        lines = ["📜 *Configured Channels:*"] + [f"{i}. `{_normalize_channel_entry(ch).get('chat_id') or _normalize_channel_entry(ch).get('invite')}`" for i, ch in enumerate(channels, 1)]
        return await query.message.reply_text("\n".join(lines), parse_mode="Markdown")

    if payload == "check_join":
        missing, check_failed = await get_missing_channels(context, uid)
        if not missing:
            if uid not in data.get("subscribers", []):
                data["subscribers"].append(uid)
                save_data(data)
            await query.message.delete()
            await query.message.reply_text("✅ Verified! You can now use the bot.")
            await query.message.reply_text(WELCOME_TEXT, parse_mode="Markdown")
        else:
            await query.message.delete()
            await prompt_user_with_missing_channels(update, context, missing, check_failed)
        return
    if payload == "force_no_invite":
        return await query.answer("⚠️ No invite URL available for this channel.", show_alert=True)

# ---------- Owner Text & File Handler (Helper Function) ----------
async def owner_flow_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Yeh function ab 'echo_message' ke dwara call kiya jaata hai
    # jab context.user_data.get("flow") set hota hai.
    
    if not context.user_data.get("flow"):
        return

    flow = context.user_data.get("flow")

    # --- 1. Broadcast Flow (Ab yeh sabhi message types ko handle karta hai) ---
    if flow == "broadcast_text":
        sent = failed = 0
        message_to_broadcast = update.message  # Bhejne waala poora message
        
        users_count = len(load_data().get("subscribers", []))
        await update.message.reply_text(f"⏳ Broadcasting message to {users_count} users...")

        for u in load_data().get("subscribers", []):
            try:
                # .copy() ka istemaal karke message ko bhejein (text, photo, file, sab kaam karega)
                await message_to_broadcast.copy(chat_id=u)
                sent += 1
            except Exception:
                failed += 1
        
        await update.message.reply_text(f"✅ Broadcast done. Sent: {sent}, Failed: {failed}", reply_markup=ReplyKeyboardRemove())
        context.user_data.clear()
        return  # Broadcast ke baad function ko rok dein

    # --- 2. File-based Flows (Database Import) ---
    if "file" in flow and update.message.document:
        # Safer file handling and robust merge response
        fname = getattr(update.message.document, "file_name", "") or ""
        if not fname.lower().endswith(".json"):
            context.user_data.clear()
            return await update.message.reply_text("❌ Invalid file. Please upload a `.json` file.", reply_markup=ReplyKeyboardRemove())

        # backup existing DB if present
        try:
            if os.path.exists(DATA_FILE):
                shutil.copyfile(DATA_FILE, LAST_BACKUP_FILE)
                await update.message.reply_text("✅ Backup of current database created.")
            else:
                await update.message.reply_text("⚠️ No existing DB found — proceeding with import.")
        except Exception as e:
            # log and continue
            print(f"[WARN] Could not create LAST_BACKUP_FILE: {e}")

        # download and parse uploaded JSON
        try:
            json_file = await update.message.document.get_file()
            file_content = await json_file.download_as_bytearray()
            new_data = json.loads(file_content.decode("utf-8"))
        except Exception as e:
            context.user_data.clear()
            return await update.message.reply_text(f"❌ Failed to read JSON file: {e}", reply_markup=ReplyKeyboardRemove())

        # Overwrite import
        if flow == "db_import_file":
            try:
                save_data(new_data)
                await update.message.reply_text("✅ Database successfully imported (overwritten).", reply_markup=ReplyKeyboardRemove())
            except Exception as e:
                await update.message.reply_text(f"❌ Failed to save imported database: {e}", reply_markup=ReplyKeyboardRemove())

        # Merge import
        elif flow == "db_import_merge_file":
            try:
                existing = load_data()
                merged, summary = merge_data(existing, new_data)
                save_data(merged)

                # Ensure summary keys exist and are ints
                new_users = int(summary.get("new_bot_users", 0) or 0)
                owners_added = int(summary.get("owners_added", 0) or 0)
                force_added = int(summary.get("force_channels_added", 0) or 0)

                # Build a Markdown-safe message (avoid accidental Markdown errors)
                summary_lines = [
                    "✅ Merge completed.",
                    "",
                    "*Merge Summary:*",
                    f"- New Bot Users: `{new_users}`",
                    f"- Owners Added: `{owners_added}`",
                    f"- Force Channels Added: `{force_added}`"
                ]
                summary_text = "\n".join(summary_lines)

                # Send as Markdown but keep it simple (numbers backticked to avoid formatting issues)
                await update.message.reply_text(summary_text, parse_mode="Markdown", reply_markup=ReplyKeyboardRemove())
            except Exception as e:
                # If anything fails, notify owner and log
                print(f"[ERROR] Merge/import failed: {e}")
                await update.message.reply_text(f"❌ Merge failed: {e}", reply_markup=ReplyKeyboardRemove())

        context.user_data.clear()
        return  # stop further processing after file flows

    # --- 3. Text-based Flows (baaki sabhi) ---
    # Agar yahan tak pahunche hain, toh hum text message expect kar rahe hain
    if not update.message or not update.message.text:
        # Agar user "Cancel" button ki jagah photo bhej de, toh usey rokein
        if flow != "broadcast_text": # Broadcast text-only nahi hai
             await update.message.reply_text("❌ Is step ke liye text ki zaroorat thi. Flow cancelled.", reply_markup=ReplyKeyboardRemove())
             context.user_data.clear()
        return

    text = update.message.text.strip()

    if text == "❌ Cancel":
        context.user_data.clear()
        return await update.message.reply_text("❌ Cancelled.", reply_markup=ReplyKeyboardRemove())

    if flow == "force_add_step1":
        entry = _normalize_channel_entry(text)
        context.user_data["force_add_entry"] = entry
        context.user_data["flow"] = "force_add_step2"
        await update.message.reply_text(
            "✅ Channel ID/Link set. Now send the button text (e.g., `Join My Channel`).",
            reply_markup=cancel_btn()
        )
        return

    completed_flow = True
    if flow == "broadcast_text":
        pass 
    
    elif flow == "mgr_add":
        try:
            new_owner_id = int(text)
            data = load_data()
            if new_owner_id not in data["owners"]:
                data["owners"].append(new_owner_id)
                save_data(data)
                await update.message.reply_text(f"✅ Added owner `{new_owner_id}`.", parse_mode="Markdown", reply_markup=ReplyKeyboardRemove())
                try:
                    await context.bot.send_message(chat_id=new_owner_id, text="🎉 Congratulations! You have been promoted to an owner of this bot.")
                except Exception as e:
                    print(f"[INFO] Could not notify new owner {new_owner_id}: {e}")
            else:
                await update.message.reply_text("This user is already an owner.", reply_markup=ReplyKeyboardRemove())
        except ValueError:
            await update.message.reply_text("❌ Invalid user ID. Please send a numeric ID.", reply_markup=ReplyKeyboardRemove())

    elif flow == "force_add_step2":
        entry = context.user_data.get("force_add_entry", {})
        entry["join_btn_text"] = text
        data = load_data()
        data.setdefault("force", {}).setdefault("channels", []).append(entry)
        save_data(data)
        await update.message.reply_text("✅ Channel added successfully!", reply_markup=ReplyKeyboardRemove())
        
    elif flow == "set_backup_interval":
        try:
            minutes = parse_interval_to_minutes(text)
            data = load_data()
            data.setdefault("auto_backup", {})["interval_minutes"] = minutes
            save_data(data)
            if data["auto_backup"].get("enabled"):
                schedule_auto_backup_job(context.application, minutes)
            await update.message.reply_text(f"✅ Interval set to {minutes} minutes.", reply_markup=ReplyKeyboardRemove())
        except Exception as e:
            await update.message.reply_text(f"❌ Invalid format: {e}", reply_markup=ReplyKeyboardRemove())
    
    else:
        completed_flow = False

    if completed_flow:
        context.user_data.clear()

# ---------- Universal Message Copier & Handlers (THE "SMART" HANDLER) ----------
async def echo_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Only handle private chats
    if update.effective_chat.type != "private": 
        return
    
    user = update.effective_user
    
    # --- Start: Owner Logic ---
    if is_owner(user.id):
        # Check if owner is in an active "flow" (like broadcast, add_owner, etc.)
        if context.user_data.get("flow"):
            # If yes, send the message to the flow handler
            await owner_flow_handler(update, context)
            return  # Aur ruk jao
        
        # Check if owner is just in "admin mode" (panel is open, but no flow active)
        if context.user_data.get('admin_mode'):
            # If yes, message ko ignore karo. (Na copy karo, na process karo)
            return  # Aur ruk jao
    # --- End: Owner Logic ---
    
    # Agar hum yahan tak pahunche hain, toh iska matlab hai:
    # 1. Yeh ek normal user hai.
    # 2. Yeh ek owner hai jo "normal mode" mein hai (na admin_mode, na koi flow).
    
    # --- Start: Normal Echo Logic (with Force Join) ---
    data = load_data()
    force = data.get("force", {})
    force_enabled = force.get("enabled", False)

    # Force-join check sirf NON-owners ke liye
    if not is_owner(user.id) and force_enabled and force.get("channels"):
        missing, _ = await get_missing_channels(context, user.id)
        if missing:
            return await prompt_user_with_missing_channels(update, context, missing)

    # Sabhi checks pass ho gaye, message ko copy karo
    try:
        await update.message.copy(chat_id=update.effective_chat.id)
    except Exception as e:
        print(f"❌ Failed to copy message via copy(): {e}")
        try:
            if update.message.text:
                await context.bot.send_message(chat_id=update.effective_chat.id, text=update.message.text)
            elif update.message.photo:
                await context.bot.send_photo(chat_id=update.effective_chat.id, photo=update.message.photo[-1].file_id, caption=update.message.caption or "")
            elif update.message.document:
                await context.bot.send_document(chat_id=update.effective_chat.id, document=update.message.document.file_id, caption=update.message.caption or "")
            elif update.message.sticker:
                await context.bot.send_sticker(chat_id=update.effective_chat.id, sticker=update.message.sticker.file_id)
            elif update.message.voice:
                await context.bot.send_voice(chat_id=update.effective_chat.id, voice=update.message.voice.file_id, caption=update.message.caption or "")
            elif update.message.audio:
                await context.bot.send_audio(chat_id=update.effective_chat.id, audio=update.message.audio.file_id, caption=update.message.caption or "")
            elif update.message.video:
                await context.bot.send_video(chat_id=update.effective_chat.id, video=update.message.video.file_id, caption=update.message.caption or "")
            elif update.message.location:
                await context.bot.send_location(chat_id=update.effective_chat.id, latitude=update.message.location.latitude, longitude=update.message.location.longitude)
            elif update.message.contact:
                c = update.message.contact
                await context.bot.send_contact(chat_id=update.effective_chat.id, phone_number=c.phone_number, first_name=c.first_name, last_name=c.last_name or "")
            elif update.message.poll:
                poll = update.message.poll
                await context.bot.send_poll(chat_id=update.effective_chat.id, question=poll.question, options=[o.text for o in poll.options], is_anonymous=poll.is_anonymous, allows_multiple_answers=poll.allows_multiple_answers)
            else:
                print("Unknown message type — cannot fallback-send.")
        except Exception as e2:
            print(f"Fallback failed too: {e2}")

async def record_chat_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not chat or chat.type not in ("group", "supergroup", "channel"): return
    data = load_data()
    known = data.setdefault("known_chats", [])
    if not any(k.get("chat_id") == chat.id for k in known):
        known.append({"chat_id": chat.id, "title": chat.title or chat.username or str(chat.id), "type": chat.type})
        save_data(data)

# ---------- Main ----------
def main():
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .read_timeout(60)
        .write_timeout(60)
        .build()
    )

    # Handler order matters:
    # 1. Groups/Channels mein chat record karna
    app.add_handler(MessageHandler((filters.ChatType.GROUP | filters.ChatType.SUPERGROUP | filters.ChatType.CHANNEL) & ~filters.COMMAND, record_chat_handler))
    
    # 2. "SMART" Handler: Yeh ab sabhi private messages (echo, admin, flows) ko handle karta hai
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND, echo_message))
    
    # owner_flow_handler yahan se HATA diya gaya hai, kyunki echo_message ab usey call karta hai.

    # 3. Command Handlers
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("owner", owner_cmd))
    
    # 4. Callback Handler (Buttons)
    app.add_handler(CallbackQueryHandler(callback_handler))

    try:
        data = load_data()
        ab = data.get("auto_backup", {})
        if ab.get("enabled", False):
            interval = int(ab.get("interval_minutes", 1))
            schedule_auto_backup_job(app, interval)
            print(f"[SCHEDULE] Auto-backup scheduled every {interval} minutes.")
    except Exception as e:
        print(f"[WARN] Could not schedule auto-backup at startup: {e}")

    print("🤖 GhostCoverBot running...")
    app.run_polling()

if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
