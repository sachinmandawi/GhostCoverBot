# -*- coding: utf-8 -*-
"""
GhostCoverBot - Force-Join (v4.6)
Author: Sachin Sir 🔥
Changes from v4.5:
 - Added explicit "Normal Mode Activated" and "Owner Mode Activated" messages for owner.
 - Cleaned up message flow for clarity.
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


async def get_missing_channels(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    data = load_data()
    force = data.get("force", {})
    raw_channels = force.get("channels", []) or []
    normalized = [_normalize_channel_entry(c) for c in raw_channels]

    if not normalized:
        return [], False

    missing = []
    check_failed_once = False
    for ch in normalized:
        query_chat = _derive_query_chat_from_entry(ch)
        if query_chat:
            try:
                member = await context.bot.get_chat_member(chat_id=query_chat, user_id=user_id)
                if member.status in ("left", "kicked"):
                    missing.append(ch)
            except Exception:
                missing.append(ch)
                check_failed_once = True
        else:
            missing.append(ch)
            check_failed_once = True
    return missing, check_failed_once


def build_join_keyboard_for_channels_list(ch_list, force_cfg):
    buttons = []
    for ch in ch_list:
        join_label = ch.get("join_btn_text") or "🔗 Join Channel"
        url = ch.get("invite")
        if not url:
            chat_id = ch.get("chat_id", "")
            if chat_id.startswith("@"):
                url = f"https://t.me/{chat_id.lstrip('@')}"

        if url:
            btn = InlineKeyboardButton(join_label, url=url)
        else:
            btn = InlineKeyboardButton(join_label, callback_data="force_no_invite")
        buttons.append(btn)

    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    check_label = force_cfg.get("check_btn_text") or "✅ Verify"
    rows.append([InlineKeyboardButton(check_label, callback_data="check_join")])
    return InlineKeyboardMarkup(rows)


async def prompt_user_with_missing_channels(update: Update, context: ContextTypes.DEFAULT_TYPE, missing_norm_list, check_failed=False):
    if not missing_norm_list:
        message_target = update.callback_query.message if update.callback_query else update.message
        if check_failed:
            await message_target.reply_text("⚠️ I couldn't verify memberships (bot may not have access). Owner, please check bot permissions.")
        else:
            await message_target.reply_text("✅ You seem to be a member of all channels.")
        return

    total = len(load_data().get("force", {}).get("channels", []))
    joined_count = max(0, total - len(missing_norm_list))
    if joined_count == 0:
        text = "🔒 *Access Restricted*\n\nYou need to join the required channels. Tap the buttons, join, then press **Verify**."
    else:
        text = "🔒 *Access Restricted*\n\nYou still need to join a few more channels. Tap below, join, then press **Verify**."

    kb = build_join_keyboard_for_channels_list(missing_norm_list, load_data().get("force", {}))
    message_target = update.callback_query.message if update.callback_query else update.message
    await message_target.reply_text(text, parse_mode="Markdown", reply_markup=kb)


# ---------- Keyboards ----------
def owner_panel_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Broadcast", callback_data="owner_broadcast"), InlineKeyboardButton("🔒 Force Join", callback_data="owner_force")],
        [InlineKeyboardButton("🧑‍💼 Manage Owner", callback_data="owner_manage")],
        [InlineKeyboardButton("⬅️ Close", callback_data="owner_close")],
    ])


def force_setting_kb(force: dict):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔁 Toggle Force-Join", callback_data="force_toggle"), InlineKeyboardButton("➕ Add Channel", callback_data="force_add")],
        [InlineKeyboardButton("🗑️ Remove Channel", callback_data="force_remove"), InlineKeyboardButton("📜 List Channel", callback_data="force_list")],
        [InlineKeyboardButton("⬅️ Back", callback_data="force_back")],
    ])


def cancel_btn():
    return ReplyKeyboardMarkup([["❌ Cancel"]], resize_keyboard=True)


# ---------- Commands ----------
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    data = load_data()

    if is_owner(user.id):
        context.user_data.clear()
        # **NEW: Send confirmation message for owner**
        await update.message.reply_text("✅ *Normal Mode Activated*\nYour messages will now be copy-forwarded.", parse_mode="Markdown")
        # The main welcome message will be sent after this

    if not is_owner(user.id):
        force = data.get("force", {})
        if force.get("enabled") and force.get("channels"):
            missing, check_failed = await get_missing_channels(context, user.id)
            if missing:
                if user.id in data.get("subscribers", []):
                    data["subscribers"].remove(user.id)
                    save_data(data)
                await prompt_user_with_missing_channels(update, context, missing, check_failed)
                return
        elif force.get("enabled"):
             await update.message.reply_text("⚠️ Force-Join is on but no channels are set. Owner, use /owner.")
             return

    if user.id not in data.get("subscribers", []):
        data["subscribers"].append(user.id)
        save_data(data)

    await update.message.reply_text(WELCOME_TEXT, parse_mode="Markdown")


async def owner_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("❌ Only owners can access this panel.")
        return
    
    context.user_data['admin_mode'] = True
    
    # **NEW: Updated message for Owner Mode**
    await update.message.reply_text(
        "✅ *Owner Mode Activated*\n\nCopy-forward is now OFF for you. Choose an option:",
        parse_mode="Markdown",
        reply_markup=owner_panel_kb()
    )


# ---------- Callback Handler ----------
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    payload = query.data
    data = load_data()

    if payload == "owner_close":
        context.user_data.clear()
        await query.message.edit_text("✅ *Normal Mode Activated*\nCopy-forward is now ON for you.", parse_mode="Markdown")
        return

    if not is_owner(uid) and payload.startswith(("owner_", "mgr_", "force_")):
        await query.message.reply_text("❌ Only owners can use these buttons.")
        return
    
    if payload == "owner_broadcast":
        context.user_data["flow"] = "broadcast_text"
        await query.message.reply_text("📢 Send the text to broadcast:", reply_markup=cancel_btn())
    
    elif payload == "owner_manage":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add Owner", callback_data="mgr_add"), InlineKeyboardButton("📜 List Owners", callback_data="mgr_list")],
            [InlineKeyboardButton("🗑️ Remove Owner", callback_data="mgr_remove"), InlineKeyboardButton("⬅️ Back", callback_data="mgr_back")],
        ])
        await query.message.edit_text("🧑‍💼 *Manage Owner*", parse_mode="Markdown", reply_markup=kb)

    elif payload == "mgr_add":
        context.user_data["flow"] = "mgr_add"
        await query.message.reply_text("➕ Send numeric user ID to add as owner:", reply_markup=cancel_btn())

    elif payload == "mgr_list":
        owners = data.get("owners", [])
        msg = "🧑‍💼 *Owners:*\n" + "\n".join([f"{i+1}. `{o}`" for i, o in enumerate(owners)])
        await query.message.reply_text(msg, parse_mode="Markdown")

    elif payload == "mgr_remove":
        owners = data.get("owners", [])
        if len(owners) <= 1:
            await query.message.reply_text("❌ At least one owner must remain.")
        else:
            kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"Remove {o}", callback_data=f"mgr_rem_{i}")] for i, o in enumerate(owners)])
            await query.message.reply_text("Select an owner to remove:", reply_markup=kb)

    elif payload.startswith("mgr_rem_"):
        try:
            idx = int(payload.split("_")[-1])
            removed = data["owners"].pop(idx)
            save_data(data)
            await query.message.reply_text(f"✅ Removed owner `{removed}`", parse_mode="Markdown")
        except (ValueError, IndexError):
            await query.message.reply_text("❌ Invalid selection.")

    elif payload == "mgr_back":
        await query.message.edit_text("✅ *Owner Mode Activated*\n\nCopy-forward is now OFF for you.", parse_mode="Markdown", reply_markup=owner_panel_kb())

    elif payload == "owner_force":
        force = data.get("force", {})
        status_text = "Enabled ✅" if force.get("enabled", False) else "Disabled ❌"
        msg = f"🔒 *Force Join Setting*\n\nStatus: `{status_text}`\n\nChoose an action:"
        await query.message.edit_text(msg, parse_mode="Markdown", reply_markup=force_setting_kb(force))

    elif payload == "force_toggle":
        force = data.setdefault("force", {})
        force["enabled"] = not force.get("enabled", False)
        save_data(data)
        status_text = "Enabled ✅" if force["enabled"] else "Disabled ❌"
        msg = f"🔒 *Force Join Setting*\n\nStatus: `{status_text}`\n\nChoose an action:"
        await query.message.edit_text(msg, parse_mode="Markdown", reply_markup=force_setting_kb(force))
        if force["enabled"] and not force.get("channels"):
            await query.message.reply_text("⚠️ Force-Join enabled but no channels configured. Add channels using Add Channel.", parse_mode="Markdown")

    elif payload == "force_add":
        context.user_data["flow"] = "force_add_step1"
        await query.message.reply_text(
            "➕ *Add Channel*\n\nSend channel ID (`@channel` or `-100...`) or an invite link.",
            parse_mode="Markdown", reply_markup=cancel_btn()
        )

    elif payload == "force_remove":
        channels = data.get("force", {}).get("channels", [])
        if not channels:
            await query.message.reply_text("ℹ️ No channels configured.")
        else:
            kb = InlineKeyboardMarkup(
                [[InlineKeyboardButton(f"Remove: {_normalize_channel_entry(ch).get('chat_id') or _normalize_channel_entry(ch).get('invite') or f'Entry {i}'}", callback_data=f"force_rem_{i}")] for i, ch in enumerate(channels)]
            )
            await query.message.reply_text("Select channel to remove:", reply_markup=kb)

    elif payload.startswith("force_rem_"):
        try:
            idx = int(payload.split("_")[-1])
            removed_ch = data["force"]["channels"].pop(idx)
            save_data(data)
            removed_id = _normalize_channel_entry(removed_ch).get('chat_id') or _normalize_channel_entry(removed_ch).get('invite')
            await query.message.reply_text(f"✅ Removed channel `{removed_id}`", parse_mode="Markdown")
        except (ValueError, IndexError):
            await query.message.reply_text("❌ Invalid selection.")

    elif payload == "force_list":
        channels = data.get("force", {}).get("channels", [])
        if not channels:
            await query.message.reply_text("ℹ️ No channels configured.")
        else:
            lines = ["📜 *Configured Channels:*"]
            for i, ch_raw in enumerate(channels, 1):
                ch = _normalize_channel_entry(ch_raw)
                lines.append(f"{i}. `ID/Link`: {ch.get('chat_id') or ch.get('invite') or 'N/A'}\n   `Button`: {ch.get('join_btn_text') or 'Default'}")
            await query.message.reply_text("\n\n".join(lines), parse_mode="Markdown")

    elif payload == "force_back":
        await query.message.edit_text("✅ *Owner Mode Activated*\n\nCopy-forward is now OFF for you.", parse_mode="Markdown", reply_markup=owner_panel_kb())

    elif payload == "force_no_invite":
        await query.message.reply_text("⚠️ No invite URL configured for this channel. Contact the owner.")

    elif payload == "check_join":
        if is_owner(uid):
            await query.message.reply_text("✅ You are an owner — access granted.")
            return

        force = data.get("force", {})
        if not force.get("enabled"):
            await query.message.reply_text("✅ Force-Join is disabled. Access granted.")
            return

        missing, check_failed = await get_missing_channels(context, uid)
        if not missing:
            if uid not in data.get("subscribers", []):
                data["subscribers"].append(uid)
                save_data(data)
            await query.message.reply_text("✅ Verified — you can now use the bot.")
            await query.message.reply_text(WELCOME_TEXT, parse_mode="Markdown")
        else:
            if uid in data.get("subscribers", []):
                data["subscribers"].remove(uid)
                save_data(data)
            await prompt_user_with_missing_channels(update, context, missing, check_failed)


# ---------- Text Message Handler ----------
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    
    if is_owner(uid) and context.user_data.get("flow"):
        data = load_data()
        text = update.message.text.strip()
        flow = context.user_data.get("flow")

        if text == "❌ Cancel":
            context.user_data.pop("flow", None)
            await update.message.reply_text("❌ Cancelled.", reply_markup=ReplyKeyboardRemove())
            return

        if flow == "broadcast_text":
            sent = failed = 0
            for u in data.get("subscribers", []):
                try:
                    await context.bot.send_message(u, text)
                    sent += 1
                except Exception:
                    failed += 1
            await update.message.reply_text(f"✅ Broadcast done. Sent: {sent}, Failed: {failed}", reply_markup=ReplyKeyboardRemove())
            context.user_data.clear()
        
        elif flow == "mgr_add":
            try:
                new_owner = int(text)
                if new_owner not in data.get("owners", []):
                    data["owners"].append(new_owner)
                    save_data(data)
                    await update.message.reply_text(f"✅ Added owner `{new_owner}`", parse_mode="Markdown", reply_markup=ReplyKeyboardRemove())
                else:
                    await update.message.reply_text("Already an owner.", reply_markup=ReplyKeyboardRemove())
                context.user_data.clear()
            except ValueError:
                await update.message.reply_text("❌ Please send a valid numeric ID.")
        
        elif flow == "force_add_step1":
            context.user_data["force_add_entry"] = {"chat_id": None, "invite": None}
            if text.startswith("http"):
                context.user_data["force_add_entry"]["invite"] = text
            else:
                context.user_data["force_add_entry"]["chat_id"] = text
            context.user_data["flow"] = "force_add_step2"
            await update.message.reply_text(f"✅ ID/Link set. Now send button text (e.g. `Join Updates`).", parse_mode="Markdown")

        elif flow == "force_add_step2":
            entry = context.user_data.get("force_add_entry")
            if entry and len(text) <= 40:
                entry["join_btn_text"] = text
                data.setdefault("force", {}).setdefault("channels", []).append(entry)
                save_data(data)
                await update.message.reply_text(f"✅ Channel added!", parse_mode="Markdown", reply_markup=ReplyKeyboardRemove())
                context.user_data.clear()
            else:
                await update.message.reply_text("❌ Error or text too long. Try again.")

        return

    await echo_message(update, context)


# ---------- Universal Message Copier (Ghost) ----------
async def echo_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
        
    user = update.effective_user
    
    if is_owner(user.id) and context.user_data.get('admin_mode'):
        return

    data = load_data()
    if not is_owner(user.id):
        force = data.get("force", {})
        if force.get("enabled") and force.get("channels"):
            missing, check_failed = await get_missing_channels(context, user.id)
            if missing:
                await prompt_user_with_missing_channels(update, context, missing, check_failed)
                return

    try:
        await update.message.copy(chat_id=update.effective_chat.id)
    except Exception:
        pass


# ---------- Run ----------
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("owner", owner_cmd))
    app.add_handler(CallbackQueryHandler(callback_handler))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(MessageHandler(filters.ALL & ~filters.TEXT & ~filters.COMMAND, echo_message))

    print("🤖 GhostCoverBot v4.6 running...")
    app.run_polling()


if __name__ == "__main__":
    main()
