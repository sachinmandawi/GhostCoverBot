# -*- coding: utf-8 -*-
"""
GhostCoverBot - Force-Join (v4.3)
Author: Sachin Sir 🔥
Changes from v4.2:
 - Fix handler ordering so ghost-copy (echo) works for all users/media.
 - Ensure owner text flows run only for owner (OWNER_ID) so they don't intercept normal messages.
 - Minor robustness improvements.
"""
import json
import os
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

# ================ CONFIG =================
BOT_TOKEN = "8001331074:AAH5XJdjO3xsCqYSQptxO8mIjRpPK9-fI5E"
OWNER_ID = 8070535163  # replace with your Telegram ID if needed
DATA_FILE = "data.json"
# =========================================

# centralized welcome text
WELCOME_TEXT = (
    "👻 *Hey there! I’m GhostCoverBot*\n\n"
    "🔹 I hide your identity like a pro.\n"
    "🔹 Just send me any message — text, photo, or video.\n"
    "🔹 I’ll instantly send it back *without forward tag!*\n\n"
    "📤 Forward it anywhere — people will think *I sent it!*"
)

DEFAULT_DATA = {
    "subscribers": [],
    "owners": [OWNER_ID],
    "force": {
        "enabled": False,
        # channels: entries may be dict {"chat_id":..., "invite":..., "join_btn_text":...}
        # or simple string "@channel" / "-100123..." / "https://t.me/..."
        "channels": [],
        "check_btn_text": "✅ Verify",
    },
}


# ---------- Storage Helpers ----------
def load_data():
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_DATA, f, indent=2)
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    # ensure required keys
    if "force" not in data:
        data["force"] = DEFAULT_DATA["force"]
    else:
        if "channels" not in data["force"]:
            data["force"]["channels"] = []
        if "check_btn_text" not in data["force"]:
            data["force"]["check_btn_text"] = DEFAULT_DATA["force"]["check_btn_text"]
    if "owners" not in data:
        data["owners"] = DEFAULT_DATA["owners"]
    if "subscribers" not in data:
        data["subscribers"] = DEFAULT_DATA["subscribers"]
    return data


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def is_owner(uid: int) -> bool:
    data = load_data()
    return uid in data.get("owners", [])


# ---------- Normalizers & Robust Helpers ----------
def _normalize_channel_entry(raw):
    """
    Accept either dict or string; returns dict with chat_id, invite, join_btn_text
    """
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
    """
    From normalized channel dict, derive a queryable chat identifier (username with @) if possible.
    Returns string (e.g., "@channelname") or None if not derivable.
    """
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


async def get_missing_channels(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """
    Returns (missing_list, check_failed_flag)
    - missing_list: list of normalized channel dicts where user is NOT member (or could not be verified)
    - check_failed_flag: True if bot couldn't attempt any membership check for any channel (rare)
    """
    data = load_data()
    force = data.get("force", {})
    raw_channels = force.get("channels", []) or []
    normalized = [_normalize_channel_entry(c) for c in raw_channels]

    if not normalized:
        return [], False  # no channels -> nothing missing

    any_check_attempted = False
    any_check_succeeded = False
    missing = []

    for ch in normalized:
        query_chat = _derive_query_chat_from_entry(ch)
        if query_chat:
            # try API check
            try:
                any_check_attempted = True
                member = await context.bot.get_chat_member(chat_id=query_chat, user_id=user_id)
                any_check_succeeded = True
                if member.status in ("left", "kicked"):
                    missing.append(ch)
                else:
                    pass
            except Exception:
                # Couldn't check (bot not in channel or invalid) -> treat as missing, but continue
                missing.append(ch)
                continue
        else:
            # No queryable username/invite; treat as missing
            missing.append(ch)

    check_failed = not any_check_attempted and any_check_succeeded is False
    return missing, check_failed


def build_join_keyboard_for_channels_list(ch_list, force_cfg):
    """
    Build a 2-column InlineKeyboardMarkup for only the channels in ch_list (normalized entries).
    Then append a single full-width Verify button at the end.
    """
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

    # arrange into 2-column rows
    rows = []
    i = 0
    while i < len(buttons):
        if i + 1 < len(buttons):
            rows.append([buttons[i], buttons[i + 1]])
            i += 2
        else:
            rows.append([buttons[i]])
            i += 1

    # verify button
    check_label = force_cfg.get("check_btn_text") or "✅ Verify"
    rows.append([InlineKeyboardButton(check_label, callback_data="check_join")])

    return InlineKeyboardMarkup(rows)


async def prompt_user_with_missing_channels(update: Update, context: ContextTypes.DEFAULT_TYPE, missing_norm_list, check_failed=False):
    """
    Show user only the missing channels' join buttons (2-column), then verify.
    If check_failed True and missing list empty -> show an informative message.
    """
    if not missing_norm_list:
        if check_failed:
            if update.callback_query:
                await update.callback_query.message.reply_text("⚠️ I couldn't verify memberships (bot may not have access). Owner, please check bot permissions.")
            else:
                await update.message.reply_text("⚠️ I couldn't verify memberships (bot may not have access). Owner, please check bot permissions.")
        else:
            if update.callback_query:
                await update.callback_query.message.reply_text("✅ You seem to be a member of all channels.")
            else:
                await update.message.reply_text("✅ You seem to be a member of all channels.")
        return

    # smart messaging: differentiate between 0 joined vs some joined
    total = len(load_data().get("force", {}).get("channels", []))
    missing_count = len(missing_norm_list)
    joined_count = max(0, total - missing_count)

    if joined_count == 0:
        # User hasn’t joined any channel yet
        text = (
            "🔒 *Access Restricted*\n\n"
            "You need to join the required channels before using the bot.\n\n"
            "Tap each **Join** button below, join those channels, and then press **Verify** to continue."
        )
    else:
        # User joined some but not all channels
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


# ---------- Keyboards ----------
def owner_panel_kb():
    kb = [
        [
            InlineKeyboardButton("📢 Broadcast", callback_data="owner_broadcast"),
            InlineKeyboardButton("🔒 Force Join Setting", callback_data="owner_force"),
        ],
        [InlineKeyboardButton("🧑‍💼 Manage Owner", callback_data="owner_manage")],
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


# ---------- Commands ----------
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    data = load_data()

    # Owner bypass
    if not is_owner(user.id):
        force = data.get("force", {})
        if force.get("enabled", False):
            if force.get("channels"):
                missing, check_failed = await get_missing_channels(context, user.id)
                if not missing:
                    # user is member of all -> ensure in subscribers
                    subs = data.setdefault("subscribers", [])
                    if user.id not in subs:
                        subs.append(user.id)
                        save_data(data)
                else:
                    # remove from subscribers if present (user not fully verified)
                    subs = data.setdefault("subscribers", [])
                    if user.id in subs:
                        subs.remove(user.id)
                        save_data(data)
                    await prompt_user_with_missing_channels(update, context, missing, check_failed)
                    return
            else:
                # no channels configured -> warn
                await update.message.reply_text("⚠️ Force-Join is enabled but no channels are configured. Owner, please configure channels via /owner.")
                return

    # normal welcome
    subs = data.setdefault("subscribers", [])
    if user.id not in subs:
        subs.append(user.id)
        save_data(data)

    await update.message.reply_text(WELCOME_TEXT, parse_mode="Markdown")


async def owner_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("❌ Only owners can access this panel.")
        return
    await update.message.reply_text("🔧 *Owner Panel*\n\nChoose an option:", parse_mode="Markdown", reply_markup=owner_panel_kb())


# ---------- Callback Handler ----------
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    payload = query.data
    data = load_data()

    # Owner panel close
    if payload == "owner_close":
        await query.message.edit_text("✅ Owner panel closed.")
        return

    # Broadcast
    if payload == "owner_broadcast":
        if not is_owner(uid):
            await query.message.reply_text("❌ Only owners can broadcast.")
            return
        context.user_data["flow"] = "broadcast_text"
        await query.message.reply_text("📢 Send the text to broadcast:", reply_markup=cancel_btn())
        return

    # Manage owner
    if payload == "owner_manage":
        if not is_owner(uid):
            await query.message.reply_text("❌ Only owners can manage owners.")
            return
        kb = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("➕ Add Owner", callback_data="mgr_add"), InlineKeyboardButton("📜 List Owners", callback_data="mgr_list")],
                [InlineKeyboardButton("🗑️ Remove Owner", callback_data="mgr_remove"), InlineKeyboardButton("⬅️ Back", callback_data="mgr_back")],
            ]
        )
        await query.message.edit_text("🧑‍💼 *Manage Owner*", parse_mode="Markdown", reply_markup=kb)
        return

    # Manage owner flows
    if payload == "mgr_add":
        context.user_data["flow"] = "mgr_add"
        await query.message.reply_text("➕ Send numeric user ID to add as owner:", reply_markup=cancel_btn())
        return

    if payload == "mgr_list":
        owners = data.get("owners", [])
        msg = "🧑‍💼 *Owners:*\n" + "\n".join([f"{i+1}. `{o}`" for i, o in enumerate(owners)])
        await query.message.reply_text(msg, parse_mode="Markdown")
        return

    if payload == "mgr_remove":
        owners = data.get("owners", [])
        if len(owners) <= 1:
            await query.message.reply_text("❌ At least one owner must remain.")
            return
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"Remove {o}", callback_data=f"mgr_rem_{i}")] for i, o in enumerate(owners)])
        await query.message.reply_text("Select an owner to remove:", reply_markup=kb)
        return

    if payload.startswith("mgr_rem_"):
        idx = int(payload.split("_")[-1])
        try:
            removed = data["owners"].pop(idx)
            save_data(data)
            await query.message.reply_text(f"✅ Removed owner `{removed}`", parse_mode="Markdown")
        except Exception:
            await query.message.reply_text("❌ Invalid selection.")
        return

    if payload == "mgr_back":
        await query.message.edit_text("🔧 *Owner Panel*\n\nChoose an option:", parse_mode="Markdown", reply_markup=owner_panel_kb())
        return

    # Enter Force Join Setting
    if payload == "owner_force":
        if not is_owner(uid):
            await query.message.reply_text("❌ Only owners can change force-join settings.")
            return
        force = data.get("force", {})
        status_text = "Enabled ✅" if force.get("enabled", False) else "Disabled ❌"
        msg = f"🔒 *Force Join Setting*\n\nStatus: `{status_text}`\n\nChoose an action:"
        await query.message.edit_text(msg, parse_mode="Markdown", reply_markup=force_setting_kb(force))
        return

    # Toggle force-join
    if payload == "force_toggle":
        if not is_owner(uid):
            await query.message.reply_text("❌ Only owners can toggle force-join.")
            return
        data = load_data()
        force = data.setdefault("force", {})
        new_state = not force.get("enabled", False)
        force["enabled"] = new_state
        save_data(data)
        status_text = "Enabled ✅" if new_state else "Disabled ❌"
        msg = f"🔒 *Force Join Setting*\n\nStatus: `{status_text}`\n\nChoose an action:"
        await query.message.edit_text(msg, parse_mode="Markdown", reply_markup=force_setting_kb(force))
        if new_state and not force.get("channels"):
            await query.message.reply_text("⚠️ Force-Join enabled but no channels configured. Add channels using Add Channel.", parse_mode="Markdown")
        return

    # Add channel (start)
    if payload == "force_add":
        if not is_owner(uid):
            await query.message.reply_text("❌ Only owners can add channels.")
            return
        context.user_data["flow"] = "force_add_step1"
        await query.message.reply_text(
            "➕ *Add Channel*\n\nSend channel identifier or invite link.\nExamples:\n - `@MyChannel`\n - `-1001234567890`\n - `https://t.me/joinchat/XXXX`",
            parse_mode="Markdown",
            reply_markup=cancel_btn(),
        )
        return

    # Remove channel (list)
    if payload == "force_remove":
        if not is_owner(uid):
            await query.message.reply_text("❌ Only owners can remove channels.")
            return
        channels = data.get("force", {}).get("channels", [])
        if not channels:
            await query.message.reply_text("ℹ️ No channels configured.")
            return
        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton(f"Remove: {ch.get('chat_id') or ch.get('invite') or str(i)}", callback_data=f"force_rem_{i}")] for i, ch in enumerate(channels)]
        )
        await query.message.reply_text("Select channel to remove:", reply_markup=kb)
        return

    if payload.startswith("force_rem_"):
        if not is_owner(uid):
            await query.message.reply_text("❌ Only owners can remove channels.")
            return
        try:
            idx = int(payload.split("_")[-1])
            channels = data.get("force", {}).get("channels", [])
            removed = channels.pop(idx)
            data["force"]["channels"] = channels
            save_data(data)
            await query.message.reply_text(f"✅ Removed channel `{removed.get('chat_id') or removed.get('invite')}`", parse_mode="Markdown")
        except Exception:
            await query.message.reply_text("❌ Invalid selection.")
        return

    # List channels
    if payload == "force_list":
        if not is_owner(uid):
            await query.message.reply_text("❌ Only owners can view channels.")
            return
        channels = data.get("force", {}).get("channels", [])
        if not channels:
            await query.message.reply_text("ℹ️ No channels configured.")
            return
        lines = ["📜 *Configured Channels:*"]
        for i, ch in enumerate(channels, start=1):
            lines.append(f"{i}. `chat_id`: `{ch.get('chat_id') or '—'}`\n   `invite`: `{ch.get('invite') or '—'}`\n   `button`: `{ch.get('join_btn_text') or '🔗 Join Channel'}`")
        await query.message.reply_text("\n\n".join(lines), parse_mode="Markdown")
        return

    # Back from force
    if payload == "force_back":
        await query.message.edit_text("🔧 *Owner Panel*\n\nChoose an option:", parse_mode="Markdown", reply_markup=owner_panel_kb())
        return

    # No invite fallback
    if payload == "force_no_invite":
        await query.message.reply_text("⚠️ No invite URL configured for this channel. Contact the owner.")
        return

    # User clicked verify
    if payload == "check_join":
        uid = query.from_user.id
        data = load_data()
        if is_owner(uid):
            await query.message.reply_text("✅ You are an owner — access granted.")
            return
        force = data.get("force", {})
        if not force.get("enabled", False):
            await query.message.reply_text("✅ Force-Join is disabled. Access granted.")
            return

        missing, check_failed = await get_missing_channels(context, uid)
        if not missing:
            subs = data.setdefault("subscribers", [])
            if uid not in subs:
                subs.append(uid)
                save_data(data)

            # Step 1: Verified message
            await query.message.reply_text("✅ Verified — you can now use the bot.")

            # Step 2: Auto send GhostCoverBot intro (welcome)
            await query.message.reply_text(WELCOME_TEXT, parse_mode="Markdown")
        else:
            # remove user from subscribers if present
            subs = data.setdefault("subscribers", [])
            if uid in subs:
                subs.remove(uid)
                save_data(data)
            if check_failed:
                await query.message.reply_text("⚠️ I couldn't fully verify memberships right now. Owner, check bot permissions.")
            else:
                # show only missing channels to user
                await prompt_user_with_missing_channels(update, context, missing, check_failed=False)
        return

    return


# ---------- Owner Text Handler (flows) ----------
async def owner_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_owner(uid):
        return
    data = load_data()
    text = update.message.text.strip()
    flow = context.user_data.get("flow")

    # Cancel
    if text == "❌ Cancel":
        context.user_data.clear()
        await update.message.reply_text("❌ Cancelled.", reply_markup=ReplyKeyboardRemove())
        return

    # Broadcast flow
    if flow == "broadcast_text":
        subs = data.get("subscribers", [])
        sent = failed = 0
        for u in subs:
            try:
                await context.bot.send_message(u, text)
                sent += 1
            except Exception:
                failed += 1
        await update.message.reply_text(f"✅ Broadcast done. Sent: {sent}, Failed: {failed}", reply_markup=ReplyKeyboardRemove())
        context.user_data.clear()
        return

    # Add owner flow
    if flow == "mgr_add":
        try:
            new_owner = int(text)
        except Exception:
            await update.message.reply_text("❌ Please send numeric ID.")
            return
        owners = data.setdefault("owners", [])
        if new_owner in owners:
            await update.message.reply_text("Already an owner.")
            context.user_data.clear()
            return
        owners.append(new_owner)
        save_data(data)
        context.user_data.clear()
        await update.message.reply_text(f"✅ Added owner `{new_owner}`", parse_mode="Markdown", reply_markup=ReplyKeyboardRemove())
        return

    # Force add - step1: received chat_id or invite
    if flow == "force_add_step1":
        entry = {"chat_id": None, "invite": None, "join_btn_text": None}
        if text.startswith("http://") or text.startswith("https://"):
            entry["invite"] = text
        else:
            entry["chat_id"] = text
        context.user_data["force_add_entry"] = entry
        context.user_data["flow"] = "force_add_step2"
        await update.message.reply_text(
            f"✅ Channel detected: `{entry.get('chat_id') or entry.get('invite')}`\n\nNow send the button text to show to users (e.g. `🔗 Join Channel` or `🚀 Join Updates`).",
            parse_mode="Markdown",
            reply_markup=cancel_btn(),
        )
        return

    # Force add - step2: received button text
    if flow == "force_add_step2":
        entry = context.user_data.get("force_add_entry")
        if not entry:
            context.user_data.clear()
            await update.message.reply_text("❌ Unexpected error. Try again.", reply_markup=ReplyKeyboardRemove())
            return
        btn = text
        if len(btn) > 40:
            await update.message.reply_text("❌ Button text too long (max 40 chars). Send shorter text.")
            return
        entry["join_btn_text"] = btn
        channels = data.setdefault("force", {}).setdefault("channels", [])
        channels.append(entry)
        data["force"]["channels"] = channels
        save_data(data)
        context.user_data.clear()
        await update.message.reply_text(
            f"✅ Channel added!\n`{entry.get('chat_id') or entry.get('invite')}`\nButton: `{btn}`",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    # default fallback
    context.user_data.clear()


# ---------- Normal Message Copier (Ghost) ----------
async def echo_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # only private chats
    if update.effective_chat.type != "private":
        return
    user = update.effective_user
    data = load_data()

    # Force-join checks for non-owners
    if not is_owner(user.id):
        force = data.get("force", {})
        if force.get("enabled", False):
            if force.get("channels"):
                missing, check_failed = await get_missing_channels(context, user.id)
                if missing:
                    # remove from subscribers if present
                    subs = data.setdefault("subscribers", [])
                    if user.id in subs:
                        subs.remove(user.id)
                        save_data(data)
                    # prompt only missing channels
                    await prompt_user_with_missing_channels(update, context, missing, check_failed)
                    return

    # Allowed to use bot — ghost-send (copy)
    try:
        # copy the incoming message back to the same chat (this removes forward tag)
        await update.message.copy(chat_id=update.effective_chat.id)
    except Exception:
        # fail silently (don't crash bot); optionally owner can be notified in future improvements
        pass


# ---------- Run ----------
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # Commands & callback handler
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("owner", owner_cmd))
    app.add_handler(CallbackQueryHandler(callback_handler))

    # Important: Owner text handler must be added BEFORE the generic echo handler
    # and must target only owner to avoid intercepting regular users' messages.
    app.add_handler(MessageHandler(filters.User(OWNER_ID) & filters.TEXT & ~filters.COMMAND, owner_text_handler))

    # Generic echo handler for everyone else (handles text/media/stickers etc.)
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, echo_message))

    print("🤖 GhostCoverBot v4.3 running...")
    app.run_polling()


if __name__ == "__main__":
    main()
