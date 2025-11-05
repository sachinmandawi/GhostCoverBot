import json
import os
import shutil
import traceback
import re
from datetime import datetime
import copy

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
    error,  # Import error module for v5 fix
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
    PicklePersistence,  # Import persistence
)

# ================ CONFIG =================
BOT_TOKEN = "8001331074:AAEQuKItN0fwOuuax0rsVVkbMlcJ05-5zKY"  # consider rotating token if production
OWNER_ID = 8070535163
PERSISTENCE_FILE = "ghostcover_bot_data.pkl"  # This will store all bot data
LAST_BACKUP_FILE = "last_backup.json"  # Still use JSON for manual backups
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
        "enabled": True,
        "channels": [
            {"chat_id": "@QorvraGroup", "invite": None, "join_btn_text": "📢 Main Group"}
        ],
        "check_btn_text": "✅ Verify",
    },
    "known_chats": [],
    "auto_backup": {
        "enabled": True,
        "interval_minutes": 1,
    },
    "sent_backup_messages": {},
    "stats": {},
}

# ---------- Local DB Helpers (Refactored) ----------
def _check_and_reset_daily_stats(data: dict):
    """Ensures today's stats entry exists. Operates on the provided dict."""
    today = datetime.now().strftime("%Y-%m-%d")
    stats = data.setdefault("stats", {})
    if today not in stats:
        stats[today] = {"new_users": 0}
    return data


def _ensure_data_keys(data: dict):
    """
    Ensures all top-level and nested keys from DEFAULT_DATA exist in bot_data.
    This is now used by post_init to set up the data on first launch.
    """
    # Use deepcopy to avoid modifying the constant
    default_copy = copy.deepcopy(DEFAULT_DATA)
    
    for key, value in default_copy.items():
        data.setdefault(key, value)
    
    # Ensure nested keys for 'force'
    force_data = data.setdefault("force", {})
    for k, v in default_copy["force"].items():
        force_data.setdefault(k, v)

    # Ensure nested keys for 'auto_backup'
    ab_data = data.setdefault("auto_backup", {})
    for k, v in default_copy["auto_backup"].items():
        ab_data.setdefault(k, v)

    # Ensure other keys are at least present
    data.setdefault("sent_backup_messages", {})
    data.setdefault("stats", {})
    return data


async def post_init(application: Application):
    """
    Populate bot_data with defaults on first run and schedule jobs.
    This runs once after the persistence is loaded but before polling.
    """
    _ensure_data_keys(application.bot_data)
    print("[INFO] Bot data initialized and keys checked.")
    
    # Schedule auto-backup (Moved from main() for correct data access)
    try:
        data = application.bot_data
        ab = data.get("auto_backup", {})
        if ab.get("enabled", False):
            interval = int(ab.get("interval_minutes", 1))
            schedule_auto_backup_job(application, interval)
            print(f"[SCHEDULE] Auto-backup scheduled every {interval} minutes.")
        else:
            print("[SCHEDULE] Auto-backup is disabled.")
    except Exception as e:
        print(f"[WARN] Could not schedule auto-backup at startup: {e}")
        

def _add_new_subscriber(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    """
    Central function to add a new user.
    Modifies context.bot_data directly.
    Returns True if a new user was added, False otherwise.
    """
    data = context.bot_data
    if user_id not in data.get("subscribers", []):
        data["subscribers"].append(user_id)
        data = _check_and_reset_daily_stats(data)
        today = datetime.now().strftime("%Y-%m-%d")
        data["stats"][today]["new_users"] += 1
        # No save_data() needed! Persistence handles it.
        return True
    return False


def is_owner(context: ContextTypes.DEFAULT_TYPE, uid: int) -> bool:
    """Checks if a user ID is in the owners list from bot_data."""
    return uid in context.bot_data.get("owners", [])

# ---------- Merge helpers (No changes needed) ----------
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

# ---------- Utility functions (Refactored) ----------
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
        
        if url:
            buttons.append(InlineKeyboardButton(join_label, url=url))
        else:
            buttons.append(InlineKeyboardButton(join_label, callback_data="force_no_invite"))
    
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    check_label = force_cfg.get("check_btn_text") or "✅ Verify"
    rows.append([InlineKeyboardButton(check_label, callback_data="check_join")])
    return InlineKeyboardMarkup(rows)


async def get_missing_channels(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """Reads from context.bot_data."""
    force = context.bot_data.get("force", {})
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
            # If no chat_id or invite link, we can't check, so assume they must join
            # This is key for the v7 fix - a badly formed entry will show up here
            missing.append(ch)
    return missing, check_failed


async def prompt_user_with_missing_channels(update: Update, context: ContextTypes.DEFAULT_TYPE, missing_norm_list, check_failed=False):
    if not missing_norm_list:
        return
    text = "🔒 *Access Restricted*\n\nYou need to join the required channels. Tap the buttons, join, then press **Verify**."
    kb = build_join_keyboard_for_channels_list(missing_norm_list, context.bot_data.get("force", {}))
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


def autobackup_kb(context: ContextTypes.DEFAULT_TYPE):
    """Reads from context.bot_data."""
    ab = context.bot_data.get("auto_backup", {})
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

# ---------- Auto-backup helpers (Refactored) ----------
def parse_interval_to_minutes(text: str) -> int:
    s = text.strip().lower()
    if s.isdigit():
        return int(s)
    total = 0
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
    """Reads from context.bot_data for backup."""
    try:
        # Data is read thread-safely from context
        data = context.bot_data
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        fname = f"auto_backup_{timestamp}.json"
        
        # Dump bot_data to the JSON backup file
        with open(fname, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
        
        # Copy to the LAST_BACKUP_FILE for the undo feature
        shutil.copyfile(fname, LAST_BACKUP_FILE)
        
        owners = data.get("owners", []) or [OWNER_ID]
        # setdefault modifies bot_data in-place, which is thread-safe
        backup_log = data.setdefault("sent_backup_messages", {})
        
        for o in owners:
            try:
                # --- Step 1: Send the new backup ---
                sent_message = await context.bot.send_document(chat_id=o, document=open(fname, "rb"), caption=f"📦 Auto-backup: {timestamp}")
                
                # --- Step 2: Log the new message ID ---
                owner_log = backup_log.setdefault(str(o), [])
                owner_log.append(sent_message.message_id)

                # --- Step 3: Try to delete the old message (v7.7 FIX) ---
                if len(owner_log) > 5:
                    try:
                        # Pop the oldest ID
                        message_to_delete = owner_log.pop(0) 
                        await context.bot.delete_message(chat_id=o, message_id=message_to_delete)
                    except Exception as delete_err:
                        # This is a non-critical error. The user probably just deleted it.
                        print(f"[INFO] Could not delete old backup message {message_to_delete} for owner {o}: {delete_err}. This is fine.")
            
            except Exception as send_err:
                # This block now *only* catches errors from Step 1 (sending)
                print(f"Failed to send backup to owner {o}: {send_err}")
        
        # No save_data() needed!
        os.remove(fname)
    except Exception as e:
        print(f"Auto-backup failed: {e}")


def schedule_auto_backup_job(application: Application, interval_minutes: int):
    # remove existing
    for j in application.job_queue.get_jobs_by_name("auto_backup"):
        j.schedule_removal()
    if interval_minutes > 0:
        application.job_queue.run_repeating(perform_and_send_backup, interval=interval_minutes * 60, first=10, name="auto_backup")
        print(f"[JOB] Auto-backup job scheduled/updated to every {interval_minutes} minutes.")
    else:
        print("[JOB] Auto-backup job removed.")

# ---------- Commands (Refactored) ----------
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    data = context.bot_data  # Use bot_data

    if is_owner(context, user.id):
        context.user_data.clear()
        await update.message.reply_text("✅ *Normal Mode Activated*\nYour messages will now be copy-forwarded.", parse_mode="Markdown")
    else:
        force = data.get("force", {})
        if force.get("enabled") and force.get("channels"):
            missing, check_failed = await get_missing_channels(context, user.id)
            if missing:
                if user.id in data.get("subscribers", []):
                    data["subscribers"].remove(user.id)  # Modifies bot_data
                await prompt_user_with_missing_channels(update, context, missing, check_failed)
                return

    # Use central function to add user and update stats
    _add_new_subscriber(context, user.id)

    await update.message.reply_text(WELCOME_TEXT, parse_mode="Markdown")


async def owner_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(context, update.effective_user.id):
        await update.message.reply_text("❌ Only owners can access this panel.")
        return
    
    context.user_data['admin_mode'] = True
    await update.message.reply_text(
        "✅ *Owner Mode Activated*\n\nCopy-forward is now OFF for you. Choose an option:",
        parse_mode="Markdown", reply_markup=owner_panel_kb()
    )

# ---------- Callback Handler (Refactored) ----------
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    payload = query.data
    data = context.bot_data  # Use bot_data

    if not is_owner(context, uid) and any(payload.startswith(p) for p in ["owner_", "db_", "mgr_", "force_"]):
        return await query.message.reply_text("❌ Only owners can use this function.")

    if payload == "owner_close":
        context.user_data.clear()
        return await query.message.edit_text("✅ *Normal Mode Activated*\nCopy-forward is now ON for you.", parse_mode="Markdown")

    if payload in ["mgr_back", "force_back", "db_back"]:
        context.user_data['admin_mode'] = True
        return await query.message.edit_text("✅ *Owner Mode Activated*\nChoose an option:", parse_mode="Markdown", reply_markup=owner_panel_kb())

    if payload == "owner_stats":
        data = _check_and_reset_daily_stats(data)  # Modifies bot_data
        today_str = datetime.now().strftime("%Y-%m-%d")
        today_stats = data.get("stats", {}).get(today_str, {"new_users": 0})
        
        # --- START V7.8 FIX ---
        # Removed the duplicate/strikethrough line
        stats_msg = (
            f"📊 *Bot Statistics*\n\n"
            f"👤 Total Users: *{len(data.get('subscribers', []))}*\n"
            f"📈 New Users Today: *{today_stats.get('new_users', 0)}*"
        )
        # --- END V7.8 FIX ---
        
        return await query.message.edit_text(stats_msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="db_back")]]))

    if payload == "owner_db":
        return await query.message.edit_text("🗄️ *Database Management*", parse_mode="Markdown", reply_markup=db_panel_kb())
    
    if payload == "db_export":
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        fname = f"backup_{timestamp}.json"
        # Dump the live bot_data to a JSON file
        with open(fname, "w", encoding="utf-8") as f: json.dump(context.bot_data, f, indent=4)
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
        current_data = context.bot_data
        
        # Create the JSON backup from live bot_data
        try:
            with open(LAST_BACKUP_FILE, "w", encoding="utf-8") as f:
                json.dump(current_data, f, indent=2)
        except Exception as e:
            print(f"Failed to create backup before clear: {e}")
            return await query.message.edit_text(f"❌ Backup failed, clear cancelled: {e}", reply_markup=db_panel_kb())

        # Reset bot_data
        new_data = copy.deepcopy(DEFAULT_DATA)
        new_data["owners"] = current_data.get("owners", [OWNER_ID])  # Preserve owners
        
        context.bot_data.clear()
        context.bot_data.update(new_data)
        
        return await query.message.edit_text("✅ Database cleared. Owners preserved. Use 'Undo' to restore.", reply_markup=db_panel_kb())
    
    if payload == "db_undo":
        if not os.path.exists(LAST_BACKUP_FILE):
            return await query.message.reply_text("ℹ️ No last backup found.", reply_markup=db_panel_kb())
        
        # --- START V7.2 FIX ---
        kb = [[InlineKeyboardButton("✅ Confirm Restore", callback_data="db_confirm_undo")], [InlineKeyboardButton("❌ Cancel", callback_data="db_back")]]
        # --- END V7.2 FIX ---
        
        return await query.message.edit_text("⚠️ *Restore Last Backup*\n\nOverwrite current DB with the last backup?", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

    if payload == "db_confirm_undo":
        try:
            # Load from the JSON backup file
            with open(LAST_BACKUP_FILE, "r", encoding="utf-8") as f:
                backup_data = json.load(f)
            
            # Overwrite the live bot_data
            context.bot_data.clear()
            context.bot_data.update(backup_data)
            _ensure_data_keys(context.bot_data)  # Ensure keys
            
            await query.message.edit_text("✅ Restored from last backup.", reply_markup=db_panel_kb())
        except Exception as e:
            await query.message.edit_text(f"❌ Restore failed: {e}", reply_markup=db_panel_kb())
        return

    if payload == "db_autobackup":
        return await query.message.edit_text("⚙️ *Auto Backup Settings*", parse_mode="Markdown", reply_markup=autobackup_kb(context))
    
    if payload == "db_backup_toggle":
        ab = data.setdefault("auto_backup", {})
        ab["enabled"] = not ab.get("enabled", False)
        # No save_data needed
        if ab["enabled"]: schedule_auto_backup_job(context.application, ab.get("interval_minutes", 1))
        else: schedule_auto_backup_job(context.application, 0)
        return await query.message.edit_text("⚙️ *Auto Backup Settings*", parse_mode="Markdown", reply_markup=autobackup_kb(context))

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
    
    # --- START V7.1 FIX ---
    if payload == "mgr_list":
        owners_list = data.get("owners", [])
        if not owners_list:
            owners_msg = "ℹ️ No owners are currently set."
        else:
            owners_msg = "🧑‍💼 *Owners:*\n" + "\n".join([f"• `{o}`" for o in owners_list])
        return await query.message.reply_text(owners_msg, parse_mode="Markdown")
    # --- END V7.1 FIX ---
    
    if payload == "mgr_remove":
        owners = data.get("owners", [])
        other_owners = [o for o in owners if o != query.from_user.id]
        
        if len(owners) <= 1:
            return await query.message.reply_text("❌ You cannot remove the last owner.")
        if not other_owners:
            return await query.message.reply_text("ℹ️ You are the only owner. No one else to remove.")
            
        kb = [[InlineKeyboardButton(f"Remove: {o}", callback_data=f"mgr_rem_id_{o}")] for o in other_owners]
        return await query.message.edit_text("Select an owner to remove:", reply_markup=InlineKeyboardMarkup(kb))
    
    if payload.startswith("mgr_rem_id_"):
        try:
            removed_id = int(payload.split("_")[-1])
        except (ValueError, IndexError):
            return await query.message.edit_text("❌ Invalid remove command.")
        
        if len(data["owners"]) <= 1:
            return await query.message.edit_text("❌ Cannot remove the last owner.", reply_markup=owner_panel_kb())

        if removed_id in data["owners"]:
            data["owners"].remove(removed_id)  # Modifies bot_data
            await query.message.edit_text(f"✅ Removed owner `{removed_id}`.", parse_mode="Markdown")
        else:
            await query.message.edit_text(f"❌ Owner `{removed_id}` not found (already removed?).", parse_mode="Markdown")

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
        # No save_data needed
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
        
        kb = []
        for ch in channels:
            norm_ch = _normalize_channel_entry(ch)
            identifier = norm_ch.get('chat_id') or norm_ch.get('invite')
            
            if identifier:
                label = f"Remove: {identifier}"
                if len(label) > 40:
                    label = label[:37] + "..."
                kb.append([InlineKeyboardButton(label, callback_data=f"force_rem_id_{identifier}")])
        
        if not kb:
            return await query.message.reply_text("ℹ️ No channels with valid identifiers found to remove.")
            
        return await query.message.edit_text("Select channel to remove:", reply_markup=InlineKeyboardMarkup(kb))

    if payload.startswith("force_rem_id_"):
        try:
            identifier_to_remove = payload[len("force_rem_id_"):]
            
            channels = data.get("force", {}).get("channels", [])
            found_index = -1
            
            for i, ch in enumerate(channels):
                norm_ch = _normalize_channel_entry(ch)
                key = norm_ch.get('chat_id') or norm_ch.get('invite')
                if str(key) == identifier_to_remove:  # Compare as strings
                    found_index = i
                    break
                    
            if found_index != -1:
                data["force"]["channels"].pop(found_index)  # Modifies bot_data
                return await query.message.edit_text(f"✅ Channel removed.", parse_mode="Markdown")
            else:
                return await query.message.edit_text("❌ Error: That channel is no longer in the list (it may have already been removed). Please try again.", reply_markup=force_setting_kb(data.get("force", {})))
        except Exception as e:
            print(f"[ERROR] in force_rem_id: {e}")
            return await query.message.edit_text("❌ Invalid remove command.")

    if payload == "force_list":
        channels = data.get("force", {}).get("channels", [])
        if not channels: return await query.message.reply_text("ℹ️ No channels configured.")
        lines = ["📜 *Configured Channels:*"] + [f"{i}. `{_normalize_channel_entry(ch).get('chat_id') or _normalize_channel_entry(ch).get('invite')}`" for i, ch in enumerate(channels, 1)]
        return await query.message.reply_text("\n".join(lines), parse_mode="Markdown")

    if payload == "check_join":
        missing, check_failed = await get_missing_channels(context, uid)
        if not missing:
            _add_new_subscriber(context, uid)
            
            await query.message.delete()
            await query.message.reply_text("✅ Verified! You can now use the bot.")
            await query.message.reply_text(WELCOME_TEXT, parse_mode="Markdown")
        else:
            await query.message.delete()
            await prompt_user_with_missing_channels(update, context, missing, check_failed)
        return
    if payload == "force_no_invite":
        return await query.answer("⚠️ No invite URL available for this channel.", show_alert=True)

# ---------- Owner Text & File Handler (Helper Function) (Refactored) ----------
async def owner_flow_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("flow"):
        return

    flow = context.user_data.get("flow")

    # --- 1. Broadcast Flow (Handles all message types) ---
    if flow == "broadcast_text":
        sent = failed = 0
        message_to_broadcast = update.message
        
        # Create a static copy to iterate over, allowing safe removal from the main list
        subscribers_list = list(context.bot_data.get("subscribers", []))
        users_count = len(subscribers_list)
        users_to_remove = []
        
        await update.message.reply_text(f"⏳ Broadcasting message to {users_count} users...")

        for u in subscribers_list:  # Iterate over the static copy
            try:
                await message_to_broadcast.copy(chat_id=u)
                sent += 1
            except error.Forbidden:
                # User blocked the bot, add to removal list
                users_to_remove.append(u)
            except Exception as e:
                # Any other error (e.g., chat not found, bot kicked)
                failed += 1
                print(f"[WARN] Broadcast to user {u} failed: {e}")
        
        # Now, safely remove all blocked users from the main bot_data list
        if users_to_remove:
            print(f"[INFO] Removing {len(users_to_remove)} blocked users from subscribers list.")
            for u in users_to_remove:
                if u in context.bot_data["subscribers"]:
                    context.bot_data["subscribers"].remove(u)
        
        failed_total = failed + len(users_to_remove)
        
        report_msg = f"✅ Broadcast done.\nSent: {sent}\nFailed: {failed_total}"
        if users_to_remove:
            report_msg += f"\n(Removed {len(users_to_remove)} blocked users.)"
            
        await update.message.reply_text(report_msg, reply_markup=ReplyKeyboardRemove())
        context.user_data.clear()
        return

    # --- 2. File-based Flows (Database Import) ---
    if "file" in flow and update.message.document:
        fname = getattr(update.message.document, "file_name", "") or ""
        if not fname.lower().endswith(".json"):
            context.user_data.clear()
            return await update.message.reply_text("❌ Invalid file. Please upload a `.json` file.", reply_markup=ReplyKeyboardRemove())

        # backup existing DB (as JSON) if present
        try:
            with open(LAST_BACKUP_FILE, "w", encoding="utf-8") as f:
                json.dump(context.bot_data, f, indent=2)
            await update.message.reply_text("✅ Backup of current database created.")
        except Exception as e:
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
                context.bot_data.clear()
                context.bot_data.update(new_data)
                _ensure_data_keys(context.bot_data)
                await update.message.reply_text("✅ Database successfully imported (overwritten).", reply_markup=ReplyKeyboardRemove())
            except Exception as e:
                await update.message.reply_text(f"❌ Failed to save imported database: {e}", reply_markup=ReplyKeyboardRemove())

        # Merge import
        elif flow == "db_import_merge_file":
            try:
                existing = context.bot_data.copy()
                merged, summary = merge_data(existing, new_data)
                
                context.bot_data.clear()
                context.bot_data.update(merged)
                _ensure_data_keys(context.bot_data)

                new_users = int(summary.get("new_bot_users", 0) or 0)
                owners_added = int(summary.get("owners_added", 0) or 0)
                force_added = int(summary.get("force_channels_added", 0) or 0)
                summary_lines = [
                    "✅ Merge completed.", "",
                    "*Merge Summary:*",
                    f"- New Bot Users: `{new_users}`",
                    f"- Owners Added: `{owners_added}`",
                    f"- Force Channels Added: `{force_added}`"
                ]
                summary_text = "\n".join(summary_lines)
                await update.message.reply_text(summary_text, parse_mode="Markdown", reply_markup=ReplyKeyboardRemove())
            except Exception as e:
                print(f"[ERROR] Merge/import failed: {e}")
                await update.message.reply_text(f"❌ Merge failed: {e}", reply_markup=ReplyKeyboardRemove())

        context.user_data.clear()
        return

    # --- 3. Text-based Flows (all remaining) ---
    if not update.message or not update.message.text:
        if flow != "broadcast_text":
            await update.message.reply_text("❌ This step required text. Flow cancelled.", reply_markup=ReplyKeyboardRemove())
            context.user_data.clear()
        return

    text = update.message.text.strip()

    if text == "❌ Cancel":
        context.user_data.clear()
        return await update.message.reply_text("❌ Cancelled.", reply_markup=ReplyKeyboardRemove())

    # --- START V7 FIX ---
    if flow == "force_add_step1":
        entry = _normalize_channel_entry(text)
        
        # Validate that the entry is usable
        if not entry.get("chat_id") and not entry.get("invite"):
            await update.message.reply_text(
                "❌ Invalid format. Please send a valid channel ID (`@channel` or `-100...`) or a full invite link (`https://t.me/...`).",
                reply_markup=cancel_btn()
            )
            # Do not advance the flow, do not clear user_data
        else:
            context.user_data["force_add_entry"] = entry
            context.user_data["flow"] = "force_add_step2"
            await update.message.reply_text(
                "✅ Channel ID/Link set. Now send the button text (e.g., `Join My Channel`).",
                reply_markup=cancel_btn()
            )
        return  # Return to wait for the next message
    # --- END V7 FIX ---

    completed_flow = True
    if flow == "broadcast_text":
        pass
    
    elif flow == "mgr_add":
        new_owner_raw = text.strip()
        if not new_owner_raw.isdigit():
            await update.message.reply_text("❌ Invalid ID. Please send a numeric User ID only.", reply_markup=cancel_btn())
            completed_flow = False
        else:
            new_owner = int(new_owner_raw)
            data = context.bot_data
            if new_owner not in data["owners"]:
                data["owners"].append(new_owner)
                await update.message.reply_text(f"✅ Added owner `{new_owner}`.", parse_mode="Markdown", reply_markup=ReplyKeyboardRemove())
                try:
                    await context.bot.send_message(chat_id=new_owner, text="🎉 Congratulations! You have been promoted to an owner of this bot.")
                except Exception as e:
                    print(f"[INFO] Could not notify new owner {new_owner}: {e}")
            else:
                await update.message.reply_text("This user is already an owner.", reply_markup=ReplyKeyboardRemove())

    elif flow == "force_add_step2":
        entry = context.user_data.get("force_add_entry", {})
        entry["join_btn_text"] = text
        data = context.bot_data
        data.setdefault("force", {}).setdefault("channels", []).append(entry)
        await update.message.reply_text("✅ Channel added successfully!", reply_markup=ReplyKeyboardRemove())
        
    elif flow == "set_backup_interval":
        try:
            minutes = parse_interval_to_minutes(text)
            data = context.bot_data
            data.setdefault("auto_backup", {})["interval_minutes"] = minutes
            if data["auto_backup"].get("enabled"):
                schedule_auto_backup_job(context.application, minutes)
            await update.message.reply_text(f"✅ Interval set to {minutes} minutes.", reply_markup=ReplyKeyboardRemove())
        except Exception as e:
            await update.message.reply_text(f"❌ Invalid format: {e}", reply_markup=ReplyKeyboardRemove())
    
    else:
        completed_flow = False

    if completed_flow:
        context.user_data.clear()

# ---------- Universal Message Copier & Handlers (Refactored) ----------
async def echo_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    
    user = update.effective_user
    
    # --- Start: Owner Logic ---
    if is_owner(context, user.id):
        if context.user_data.get("flow"):
            await owner_flow_handler(update, context)
            return
        
        if context.user_data.get('admin_mode'):
            return
    # --- End: Owner Logic ---
    
    # --- Start: Normal Echo Logic (with Force Join) ---
    data = context.bot_data
    force = data.get("force", {})
    force_enabled = force.get("enabled", False)

    if not is_owner(context, user.id) and force_enabled and force.get("channels"):
        missing, _ = await get_missing_channels(context, user.id)
        if missing:
            # --- START V6 FIX ---
            # If a user was previously subscribed but is now non-compliant
            # (e.g., admin added a new channel), remove them until they re-verify.
            # This matches the logic in start_cmd.
            if user.id in data.get("subscribers", []):
                data["subscribers"].remove(user.id)
            # --- END V6 FIX ---
            return await prompt_user_with_missing_channels(update, context, missing)

    try:
        await update.message.copy(chat_id=update.effective_chat.id)
    except Exception as e:
        print(f"❌ Failed to copy message via copy() for user {user.id}: {e}")

async def record_chat_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not chat or chat.type not in ("group", "supergroup", "channel"): return
    data = context.bot_data
    known = data.setdefault("known_chats", [])
    if not any(k.get("chat_id") == chat.id for k in known):
        known.append({"chat_id": chat.id, "title": chat.title or chat.username or str(chat.id), "type": chat.type})
        # No save_data needed

# ---------- Main (Refactored) ----------
def main():
    # Create the persistence object
    persistence = PicklePersistence(filepath=PERSISTENCE_FILE)

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .persistence(persistence)  # Add persistence
        .post_init(post_init)      # Add post_init setup
        .read_timeout(60)
        .write_timeout(60)
        .build()
    )

    # Handler order matters:
    # 1. Record chat info in groups/channels
    app.add_handler(MessageHandler((filters.ChatType.GROUP | filters.ChatType.SUPERGROUP | filters.ChatType.CHANNEL) & ~filters.COMMAND, record_chat_handler))
    
    # 2. "SMART" Handler: This now handles all private messages (echo, admin, flows)
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND, echo_message))
    
    # 3. Command Handlers
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("owner", owner_cmd))
    
    # 4. Callback Handler (Buttons)
    app.add_handler(CallbackQueryHandler(callback_handler))

    # Auto-backup scheduling is now handled in post_init()
    # to ensure persistence is loaded first.

    print("🤖 GhostCoverBot running with PicklePersistence...")
    app.run_polling()

if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
