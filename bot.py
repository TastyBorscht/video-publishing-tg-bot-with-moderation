"""
Main bot module for video submission and moderation system.
Implements all steps from prompt2 with security and error handling.
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from telegram.error import TelegramError, BadRequest

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

import config
from database import Database
from localization import t, init_localization

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Global database instance
db: Optional[Database] = None
scheduler: Optional[AsyncIOScheduler] = None

# Initialize localization
init_localization()


# ============================================================================
# STEP 1: User video submission
# ============================================================================

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle video submission from users."""
    if update.message.chat.type != "private":
        return  # Only process videos in private chat

    user = update.message.from_user
    video = update.message.video

    if not video:
        await update.message.reply_text(t("send_video_prompt", "Please send a video file"))
        return

    # Check if user is blacklisted
    if await db.is_blacklisted(user.id):
        await update.message.reply_text(
            t("user_blacklisted", "❌ You are not allowed to submit videos.")
        )
        logger.info(f"Blacklisted user {user.id} attempted to submit video")
        return

    # Store video in database with pending status
    video_id = await db.insert_video(
        file_id=video.file_id,
        user_id=user.id,
        username=user.username or user.first_name,
        is_anonymous=False,  # Will be updated based on button click
        status="pending",
        user_message_id=update.message.message_id
    )

    # Create inline buttons for user choice
    keyboard = [
        [
            InlineKeyboardButton(t("button_publish_publicly", "Publish publicly"), callback_data=f"pub_public_{video_id}"),
            InlineKeyboardButton(t("button_publish_anonymously", "Publish anonymously"), callback_data=f"pub_anon_{video_id}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Send button message
    button_message = await update.message.reply_text(
        t("choose_publication_type", "Choose publication type:"),
        reply_markup=reply_markup
    )

    # Schedule deletion after 1 minute if no button is clicked
    context.job_queue.run_once(
        timeout_video_submission,
        when=config.SUBMISSION_TIMEOUT_SECONDS,
        data={
            "user_id": user.id,
            "video_message_id": update.message.message_id,
            "button_message_id": button_message.message_id,
            "video_id": video_id,
            "chat_id": update.message.chat_id
        }
    )

    logger.info(f"Video received from user {user.id}, video_id={video_id}")


async def timeout_video_submission(context: ContextTypes.DEFAULT_TYPE):
    """Delete video and button messages after timeout."""
    job_data = context.job.data
    chat_id = job_data["chat_id"]
    video_id = job_data["video_id"]

    # Check if video is still pending
    video = await db.get_video_by_id(video_id)
    if video and video["status"] == "pending":
        try:
            # Delete messages
            await context.bot.delete_message(
                chat_id=chat_id,
                message_id=job_data["video_message_id"]
            )
            await context.bot.delete_message(
                chat_id=chat_id,
                message_id=job_data["button_message_id"]
            )
            # Delete or update database record
            await db.delete_video(video_id)
            logger.info(f"Timeout: Deleted video {video_id} due to no response")
        except TelegramError as e:
            logger.error(f"Error deleting timeout messages: {e}")


async def handle_publication_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle user's choice of public/anonymous publication."""
    query = update.callback_query
    await query.answer()

    data = query.data
    if not data.startswith("pub_"):
        return

    parts = data.split("_")
    pub_type = parts[1]  # "public" or "anon"
    video_id = int(parts[2])

    # Get video from database
    video = await db.get_video_by_id(video_id)
    if not video or video["status"] != "pending":
        await query.answer(t("error_video_processed_or_timeout", "This video has already been processed or timed out"), show_alert=True)
        return

    # Update anonymity status
    is_anonymous = (pub_type == "anon")
    await db.update_status(video_id, "pending", is_anonymous=is_anonymous)

    # Prepare caption for moderation group (includes user ID)
    if is_anonymous:
        caption = t("caption_anonymous_user", "Video from anonymous user")
    else:
        username = video["username"]
        if username and not username.startswith("@"):
            username = f"@{username}" if username else username
        caption = f"Video from user {username}"

    # Add user ID for moderators (visible only in moderation group)
    moderation_caption = f"{caption}\n\n👤 User ID: `{video['user_id']}`"

    # Forward to moderation group
    try:
        sent_message = await context.bot.send_video(
            chat_id=config.MODERATION_GROUP_ID,
            video=video["file_id"],
            caption=moderation_caption,
            parse_mode='Markdown'
        )

        # Add moderation buttons
        keyboard = [
            [
                InlineKeyboardButton(t("button_approve", "Approve"), callback_data=f"mod_approve_{video_id}"),
                InlineKeyboardButton(t("button_reject", "Reject"), callback_data=f"mod_reject_{video_id}")
            ],
            [
                InlineKeyboardButton(t("button_schedule", "Schedule"), callback_data=f"mod_schedule_{video_id}"),
                InlineKeyboardButton(t("button_publish_now", "Publish now"), callback_data=f"mod_publish_{video_id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await context.bot.edit_message_reply_markup(
            chat_id=config.MODERATION_GROUP_ID,
            message_id=sent_message.message_id,
            reply_markup=reply_markup
        )

        # Update database with moderation message ID and new file_id
        await db.update_status(
            video_id,
            "pending",
            moderation_message_id=sent_message.message_id,
            file_id=sent_message.video.file_id
        )

        # Confirm to user
        await context.bot.send_message(
            chat_id=video["user_id"],
            text=t("video_sent_to_moderation", "Your video has been sent.")
        )

        # Delete original messages
        await context.bot.delete_message(
            chat_id=query.message.chat_id,
            message_id=video["user_message_id"]
        )
        await query.message.delete()

        logger.info(f"Video {video_id} sent to moderation group")

    except TelegramError as e:
        logger.error(f"Error sending video to moderation group: {e}")
        await query.answer(t("error_sending_to_moderation", "Error sending video to moderation. Please try again."), show_alert=True)


# ============================================================================
# STEP 2: Moderation group handlers
# ============================================================================

def is_moderator(user_id: int, chat_id: int) -> bool:
    """
    CRITICAL SECURITY CHECKS:
    1. Verify user_id is in MODERATOR_IDS
    2. Verify chat_id is MODERATION_GROUP_ID (prevent forwarded message exploitation)
    """
    return (user_id in config.MODERATOR_IDS and
            chat_id == config.MODERATION_GROUP_ID)


async def handle_moderation_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle moderation button clicks with security checks."""
    query = update.callback_query

    # CRITICAL SECURITY CHECKS
    if not is_moderator(query.from_user.id, query.message.chat_id):
        await query.answer(
            t("error_unauthorized_action", "You are not authorized to perform this action."),
            show_alert=True
        )
        return

    data = query.data
    if not data.startswith("mod_"):
        await query.answer()
        return

    parts = data.split("_")
    action = parts[1]  # "approve", "reject", "schedule", "publish"
    video_id = int(parts[2])

    # Get video from database
    video = await db.get_video_by_id(video_id)
    if not video:
        await query.answer(t("error_video_not_found", "Video not found in database"), show_alert=True)
        return

    # Check if already processed (allow edit for queued/scheduled)
    if action == "edit":
        # Edit button works for pending, queued, and scheduled videos
        if video["status"] not in ["pending", "queued", "scheduled"]:
            await query.answer(
                "This video has already been published or rejected",
                show_alert=True
            )
            return
    else:
        # Other actions only work for pending and queued videos
        if video["status"] not in ["pending", "queued"]:
            await query.answer(
                "This video has already been processed",
                show_alert=True
            )
            return

    # Answer the callback query before processing
    await query.answer()

    # Route to appropriate handler
    if action == "approve":
        await moderate_approve(query, context, video)
    elif action == "reject":
        await moderate_reject(query, context, video)
    elif action == "schedule":
        await moderate_schedule(query, context, video)
    elif action == "publish":
        await moderate_publish_now(query, context, video)
    elif action == "edit":
        await moderate_edit_cancel(query, context, video)


async def moderate_edit_cancel(query, context: ContextTypes.DEFAULT_TYPE, video: dict):
    """Edit/Cancel a queued or scheduled video - return to original moderation menu."""
    video_id = video["id"]

    try:
        # Reset status to pending
        await db.update_status(video_id, "pending", scheduled_time=None)

        # Get the original caption (remove status messages, keep user ID)
        if video['is_anonymous']:
            caption_base = t("caption_anonymous_user", "Video from anonymous user")
        else:
            username = video["username"]
            if username and not username.startswith("@"):
                username = f"@{username}"
            caption_base = f"Video from user {username}"

        # Add user ID for moderators
        moderation_caption = f"{caption_base}\n\n👤 User ID: `{video['user_id']}`"

        # Restore original moderation buttons
        keyboard = [
            [
                InlineKeyboardButton("Approve", callback_data=f"mod_approve_{video_id}"),
                InlineKeyboardButton("Reject", callback_data=f"mod_reject_{video_id}")
            ],
            [
                InlineKeyboardButton("Schedule", callback_data=f"mod_schedule_{video_id}"),
                InlineKeyboardButton("Publish now", callback_data=f"mod_publish_{video_id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.message.edit_caption(
            caption=moderation_caption,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

        logger.info(f"Video {video_id} reset to pending - returned to moderation menu")
    except TelegramError as e:
        logger.error(f"Error resetting video {video_id}: {e}")
        try:
            await query.message.edit_caption(
                caption=f"{query.message.caption}\n\n❌ Error: {str(e)}"
            )
        except:
            pass


async def moderate_approve(query, context: ContextTypes.DEFAULT_TYPE, video: dict):
    """Approve video and add to queue (Step 3)."""
    video_id = video["id"]

    try:
        # Update status to queued
        await db.update_status(video_id, "queued")

        # Update message caption and add Edit/Cancel button
        keyboard = [[InlineKeyboardButton("🔄 Edit/Cancel", callback_data=f"mod_edit_{video_id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.message.edit_caption(
            caption=f"{query.message.caption}\n\n✅ Video is queued for publication",
            reply_markup=reply_markup
        )

        # Notify user
        try:
            await context.bot.send_message(
                chat_id=video["user_id"],
                text=t("video_approved_queued", "Your video has been approved and added to the publication queue.")
            )
        except TelegramError as e:
            logger.error(f"Failed to notify user {video['user_id']}: {e}")

        logger.info(f"Video {video_id} approved and queued")
    except TelegramError as e:
        logger.error(f"Error approving video {video_id}: {e}")
        try:
            await query.message.edit_caption(
                caption=f"{query.message.caption}\n\n❌ Error: {str(e)}"
            )
        except:
            pass


async def moderate_reject(query, context: ContextTypes.DEFAULT_TYPE, video: dict):
    """Reject video and delete from moderation group (Step 2b)."""
    video_id = video["id"]

    try:
        # Update status to rejected
        await db.update_status(
            video_id,
            "rejected",
            rejected_at=datetime.now()
        )

        # Delete message from moderation group
        await query.message.delete()

        # Notify user
        await context.bot.send_message(
            chat_id=video["user_id"],
            text=t("video_not_approved", "Your video was not approved for publication.")
        )

        logger.info(f"Video {video_id} rejected")
    except TelegramError as e:
        logger.error(f"Error rejecting video {video_id}: {e}")
        # Try to edit the message to show error since we can't delete it
        try:
            await query.message.edit_caption(
                caption=f"{query.message.caption}\n\n❌ Error deleting: {str(e)}"
            )
        except:
            pass


async def moderate_schedule(query, context: ContextTypes.DEFAULT_TYPE, video: dict):
    """
    Schedule video for specific time (Step 4).
    Shows buttons for quick scheduling and date/time selection
    """
    video_id = video["id"]

    try:
        now = datetime.now(config.TIMEZONE)

        # Create inline buttons for scheduling options
        keyboard = [
            [InlineKeyboardButton("⚡ Quick Schedule", callback_data=f"schedmenu_{video_id}_quick")],
            [InlineKeyboardButton("📅 Choose Date", callback_data=f"schedmenu_{video_id}_date")],
            [InlineKeyboardButton("❌ Cancel", callback_data=f"sched_{video_id}_cancel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.message.reply_text(
            f"⏰ Schedule video {video_id} for publication\n"
            f"Current time: {now.strftime('%Y-%m-%d %H:%M %Z')}\n\n"
            f"Choose scheduling method:",
            reply_markup=reply_markup
        )

        logger.info(f"Scheduling menu shown for video {video_id}")
    except TelegramError as e:
        logger.error(f"Error showing schedule menu for video {video_id}: {e}")
        try:
            await query.message.edit_caption(
                caption=f"{query.message.caption}\n\n❌ Error: {str(e)}"
            )
        except:
            pass


async def handle_schedule_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle schedule submenu selection."""
    query = update.callback_query

    logger.info(f"handle_schedule_menu called with data: {query.data}")

    # CRITICAL SECURITY CHECKS
    if not is_moderator(query.from_user.id, query.message.chat_id):
        await query.answer(t("error_unauthorized_action", "You are not authorized to perform this action."), show_alert=True)
        return

    data = query.data
    if not data.startswith("schedmenu_"):
        await query.answer()
        return

    await query.answer()

    parts = data.split("_")
    video_id = int(parts[1])
    menu_type = parts[2]

    logger.info(f"Schedule menu type: {menu_type} for video {video_id}")

    if menu_type == "quick":
        # Show quick schedule buttons
        keyboard = [
            [
                InlineKeyboardButton("+1 hour", callback_data=f"sched_{video_id}_1"),
                InlineKeyboardButton("+2 hours", callback_data=f"sched_{video_id}_2"),
                InlineKeyboardButton("+3 hours", callback_data=f"sched_{video_id}_3")
            ],
            [
                InlineKeyboardButton("+6 hours", callback_data=f"sched_{video_id}_6"),
                InlineKeyboardButton("+12 hours", callback_data=f"sched_{video_id}_12"),
                InlineKeyboardButton("+24 hours", callback_data=f"sched_{video_id}_24")
            ],
            [
                InlineKeyboardButton("⬅️ Back", callback_data=f"schedback_{video_id}"),
                InlineKeyboardButton("❌ Cancel", callback_data=f"sched_{video_id}_cancel")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(
            f"⚡ Quick Schedule - Video {video_id}\n"
            f"Select time from now:",
            reply_markup=reply_markup
        )

    elif menu_type == "date":
        # Show date picker (next 7 days)
        now = datetime.now(config.TIMEZONE)
        keyboard = []

        for i in range(7):
            future_date = now + timedelta(days=i)
            label = "Today" if i == 0 else "Tomorrow" if i == 1 else future_date.strftime("%a, %b %d")
            keyboard.append([
                InlineKeyboardButton(label, callback_data=f"scheddate_{video_id}_{i}")
            ])

        keyboard.append([
            InlineKeyboardButton("⬅️ Back", callback_data=f"schedback_{video_id}"),
            InlineKeyboardButton("❌ Cancel", callback_data=f"sched_{video_id}_cancel")
        ])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(
            f"📅 Choose Date - Video {video_id}\n"
            f"Select a date:",
            reply_markup=reply_markup
        )


async def handle_schedule_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle date selection for scheduling."""
    query = update.callback_query

    # CRITICAL SECURITY CHECKS
    if not is_moderator(query.from_user.id, query.message.chat_id):
        await query.answer(t("error_unauthorized_action", "You are not authorized to perform this action."), show_alert=True)
        return

    data = query.data
    if not data.startswith("scheddate_"):
        await query.answer()
        return

    await query.answer()

    parts = data.split("_")
    video_id = int(parts[1])
    days_offset = int(parts[2])

    # Show time picker for selected date
    now = datetime.now(config.TIMEZONE)
    selected_date = now + timedelta(days=days_offset)

    keyboard = []

    # Generate time slots (every 2 hours from 8:00 to 22:00)
    for hour in range(8, 23, 2):
        time_str = f"{hour:02d}:00"
        keyboard.append([
            InlineKeyboardButton(time_str, callback_data=f"schedtime_{video_id}_{days_offset}_{hour}")
        ])

    keyboard.append([
        InlineKeyboardButton("⬅️ Back", callback_data=f"schedmenu_{video_id}_date"),
        InlineKeyboardButton("❌ Cancel", callback_data=f"sched_{video_id}_cancel")
    ])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(
        f"🕐 Choose Time - Video {video_id}\n"
        f"Date: {selected_date.strftime('%Y-%m-%d')}\n"
        f"Select a time:",
        reply_markup=reply_markup
    )


async def handle_schedule_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle schedule time selection buttons."""
    query = update.callback_query

    # CRITICAL SECURITY CHECKS
    if not is_moderator(query.from_user.id, query.message.chat_id):
        await query.answer(
            t("error_unauthorized_action", "You are not authorized to perform this action."),
            show_alert=True
        )
        return

    data = query.data

    # Handle "Back" button
    if data.startswith("schedback_"):
        video_id = int(data.split("_")[1])
        video = await db.get_video_by_id(video_id)
        if video:
            await query.answer()
            # Re-show main schedule menu
            await moderate_schedule(query, context, video)
        return

    if not data.startswith("sched_") and not data.startswith("schedtime_"):
        await query.answer()
        return

    # Handle schedtime_ (specific date/time selection)
    if data.startswith("schedtime_"):
        parts = data.split("_")
        video_id = int(parts[1])
        days_offset = int(parts[2])
        hour = int(parts[3])

        # Calculate scheduled time
        now = datetime.now(config.TIMEZONE)
        scheduled_time = now + timedelta(days=days_offset)
        scheduled_time = scheduled_time.replace(hour=hour, minute=0, second=0, microsecond=0)

        # If the time is in the past today, show error
        if scheduled_time <= now:
            await query.answer(t("error_time_in_past", "Selected time is in the past. Please choose a future time."), show_alert=True)
            return

        hours_str = None  # Will use scheduled_time directly
    else:
        # Handle sched_ (quick schedule)
        parts = data.split("_")
        video_id = int(parts[1])
        hours_str = parts[2]
        scheduled_time = None  # Will calculate from hours_str

    # Get video from database
    video = await db.get_video_by_id(video_id)
    if not video:
        await query.answer(t("error_video_not_found", "Video not found in database"), show_alert=True)
        return

    # Check if already processed
    if video["status"] not in ["pending", "queued"]:
        await query.answer(
            "This video has already been processed",
            show_alert=True
        )
        return

    await query.answer()

    # Handle cancel
    if hours_str == "cancel":
        await query.message.delete()
        logger.info(f"Schedule cancelled for video {video_id}")
        return

    try:
        # Calculate scheduled time if not already set
        if scheduled_time is None:
            hours = int(hours_str)
            scheduled_time = datetime.now(config.TIMEZONE) + timedelta(hours=hours)

        # Update video status to scheduled
        await db.update_status(
            video_id,
            "scheduled",
            scheduled_time=scheduled_time.replace(tzinfo=None).isoformat()
        )

        # Update moderation message caption (keep User ID)
        # Get the current caption from the video record
        if video['is_anonymous']:
            caption_base = t("caption_anonymous_user", "Video from anonymous user")
        else:
            username = video["username"]
            if username and not username.startswith("@"):
                username = f"@{username}"
            caption_base = f"Video from user {username}"

        # Add User ID and scheduled time
        moderation_caption = (
            f"{caption_base}\n\n"
            f"👤 User ID: `{video['user_id']}`\n\n"
            f"📅 Scheduled for: {scheduled_time.strftime('%Y-%m-%d %H:%M %Z')}"
        )

        # Add Edit/Cancel button
        keyboard = [[InlineKeyboardButton("🔄 Edit/Cancel", callback_data=f"mod_edit_{video_id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await context.bot.edit_message_caption(
            chat_id=config.MODERATION_GROUP_ID,
            message_id=video["moderation_message_id"],
            caption=moderation_caption,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

        # Delete schedule menu
        await query.message.delete()

        # Notify user
        try:
            await context.bot.send_message(
                chat_id=video["user_id"],
                text=t("video_scheduled_notification", "Your video has been scheduled for publication on {scheduled_time}.",
                      scheduled_time=scheduled_time.strftime('%Y-%m-%d at %H:%M %Z'))
            )
        except TelegramError as e:
            logger.error(f"Failed to notify user {video['user_id']}: {e}")

        logger.info(f"Video {video_id} scheduled for {scheduled_time}")
    except Exception as e:
        logger.error(f"Error scheduling video {video_id}: {e}")
        await query.message.edit_text(t("error_scheduling_video", "❌ Error scheduling video: {error}", error=str(e)))


async def moderate_publish_now(query, context: ContextTypes.DEFAULT_TYPE, video: dict):
    """Publish video immediately to target channel (Step 5)."""
    video_id = video["id"]

    try:
        logger.info(f"Attempting to publish video {video_id} immediately")
        success = await publish_video_to_channel(context, video)

        if success:
            # Update status to published
            await db.update_status(
                video_id,
                "published",
                published_at=datetime.now()
            )

            # Delete moderation message
            await query.message.delete()

            # Notify user
            try:
                await context.bot.send_message(
                    chat_id=video["user_id"],
                    text=t("video_published", "Your video has been published.")
                )
            except TelegramError as e:
                logger.error(f"Failed to notify user {video['user_id']}: {e}")

            logger.info(f"Video {video_id} published immediately")
        else:
            logger.error(f"Failed to publish video {video_id}")
            # Edit message to show failure
            try:
                await query.message.edit_caption(
                    caption=f"{query.message.caption}\n\n❌ Failed to publish video"
                )
            except:
                pass
    except TelegramError as e:
        logger.error(f"Error in moderate_publish_now for video {video_id}: {e}")
        # Try to edit the message to show error
        try:
            await query.message.edit_caption(
                caption=f"{query.message.caption}\n\n❌ Error: {str(e)}"
            )
        except:
            pass


# ============================================================================
# STEP 3: Queue publication system
# ============================================================================

async def publish_from_queue(context: ContextTypes.DEFAULT_TYPE):
    """
    Publish next video from queue.
    Runs based on PUBLISH_INTERVAL_MINUTES during publishing window (08:00-23:00 Moscow time).
    """
    # Check if we're in publishing window
    now = datetime.now(config.TIMEZONE)
    current_hour = now.hour

    logger.info(f"Queue check triggered at {now.strftime('%Y-%m-%d %H:%M:%S')} Moscow time")

    if not (config.PUBLISH_HOURS_START <= current_hour <= config.PUBLISH_HOURS_END):
        logger.info(f"Outside publishing window (current: {current_hour}:00, window: {config.PUBLISH_HOURS_START}:00-{config.PUBLISH_HOURS_END}:00), skipping")
        return

    # Get next video from queue
    video = await db.get_next_queued_video()
    if not video:
        logger.info("Queue is empty, no videos to publish")
        return

    logger.info(f"Found video {video['id']} in queue, attempting to publish...")

    # Publish video
    success = await publish_video_to_channel(context, video)

    if success:
        # Update status to published
        await db.update_status(
            video["id"],
            "published",
            published_at=datetime.now()
        )

        # Delete moderation message
        try:
            await context.bot.delete_message(
                chat_id=config.MODERATION_GROUP_ID,
                message_id=video["moderation_message_id"]
            )
            logger.info(f"Deleted moderation message {video['moderation_message_id']} for video {video['id']}")
        except TelegramError as e:
            logger.error(f"Error deleting moderation message {video['moderation_message_id']}: {e}")

        # Notify user
        try:
            await context.bot.send_message(
                chat_id=video["user_id"],
                text=t("video_published", "Your video has been published.")
            )
        except TelegramError as e:
            logger.error(f"Failed to notify user {video['user_id']}: {e}")

        logger.info(f"Video {video['id']} published from queue")
    else:
        logger.error(f"Failed to publish video {video['id']} from queue")


# ============================================================================
# STEP 4 & 6: Scheduled publication and publication helper
# ============================================================================

async def publish_video_to_channel(
    context: ContextTypes.DEFAULT_TYPE,
    video: dict
) -> bool:
    """
    Publish video to target channel with retry logic.
    Returns True if successful, False otherwise.
    """
    for attempt in range(config.RETRY_ATTEMPTS):
        try:
            # Determine caption
            if video["is_anonymous"]:
                caption = t("caption_anonymous_user", "Video from anonymous user")
            else:
                username = video["username"]
                if username and not username.startswith("@"):
                    username = f"@{username}"
                caption = f"Video from user {username}"

            # Send video to target channel
            await context.bot.send_video(
                chat_id=config.TARGET_CHANNEL_ID,
                video=video["file_id"],
                caption=caption
            )

            logger.info(f"Video {video['id']} published to channel successfully")
            return True

        except BadRequest as e:
            # Video deleted from Telegram
            logger.error(f"Video {video['id']} unavailable (deleted): {e}")
            await db.update_status(video["id"], "failed")
            return False

        except TelegramError as e:
            logger.error(f"Attempt {attempt + 1}/{config.RETRY_ATTEMPTS} failed for video {video['id']}: {e}")
            if attempt < config.RETRY_ATTEMPTS - 1:
                await asyncio.sleep(config.RETRY_DELAY_SECONDS)
            else:
                logger.error(f"All retry attempts failed for video {video['id']}")
                await db.update_status(video["id"], "failed")
                return False

    return False


async def check_scheduled_videos(context: ContextTypes.DEFAULT_TYPE):
    """Check and publish scheduled videos with 30-minute delay for overdue videos."""
    now = datetime.now(config.TIMEZONE)
    videos = await db.get_scheduled_videos()

    if not videos:
        return

    # Separate overdue and on-time videos
    overdue_videos = []

    for video in videos:
        scheduled_time = datetime.fromisoformat(video["scheduled_time"])
        scheduled_time = config.TIMEZONE.localize(scheduled_time)

        time_diff = (now - scheduled_time).total_seconds()

        if time_diff > 0:  # Video is overdue
            overdue_videos.append((video, scheduled_time, time_diff))

    # Sort overdue videos by scheduled time (oldest first)
    overdue_videos.sort(key=lambda x: x[1])

    # Handle overdue videos with 30-minute staggered publishing
    if overdue_videos:
        last_overdue_publish = context.bot_data.get('last_overdue_scheduled_publish')

        if last_overdue_publish:
            minutes_since_last = (now - last_overdue_publish).total_seconds() / 60
            if minutes_since_last < 30:
                logger.info(f"Waiting for 30-minute gap - last overdue video published {minutes_since_last:.1f} minutes ago")
                return

        # Publish the oldest overdue video
        video, scheduled_time, time_overdue = overdue_videos[0]
        hours_overdue = time_overdue / 3600

        logger.info(f"Publishing overdue scheduled video {video['id']} (was scheduled for {scheduled_time}, {hours_overdue:.1f} hours late)")
        success = await publish_video_to_channel(context, video)

        if success:
            await db.update_status(
                video["id"],
                "published",
                published_at=datetime.now()
            )

            # Delete moderation message
            try:
                await context.bot.delete_message(
                    chat_id=config.MODERATION_GROUP_ID,
                    message_id=video["moderation_message_id"]
                )
                logger.info(f"Deleted moderation message {video['moderation_message_id']} for scheduled video {video['id']}")
            except TelegramError as e:
                logger.error(f"Error deleting moderation message {video['moderation_message_id']}: {e}")

            # Notify user
            try:
                await context.bot.send_message(
                    chat_id=video["user_id"],
                    text=t("video_published", "Your video has been published.")
                )
            except TelegramError as e:
                logger.error(f"Failed to notify user {video['user_id']}: {e}")

            # Record publish time
            context.bot_data['last_overdue_scheduled_publish'] = now
            logger.info(f"Scheduled video {video['id']} published")

            # Log remaining overdue videos
            if len(overdue_videos) > 1:
                logger.info(f"Still {len(overdue_videos) - 1} overdue scheduled video(s) waiting (30-minute gap between publications)")
        else:
            logger.error(f"Failed to publish scheduled video {video['id']}")


# ============================================================================
# Bot initialization and startup
# ============================================================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    await update.message.reply_text(
        t("welcome_message",
          "Welcome to the Video Submission Bot!\n\n"
          "Send me a video to submit it for publication.")
    )


async def approve_all_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /a command - approve all pending videos in moderation group."""
    # Only work in moderation group
    if update.message.chat_id != config.MODERATION_GROUP_ID:
        return

    # Check if user is moderator
    if not is_moderator(update.message.from_user.id, update.message.chat_id):
        await update.message.reply_text(t("unauthorized_command", "❌ You are not authorized to use this command."))
        return

    try:
        # Get all pending videos
        pending_videos = await db.get_pending_videos()

        if not pending_videos:
            await update.message.reply_text(t("no_pending_videos", "ℹ️ No pending videos to approve."))
            return

        approved_count = 0
        failed_count = 0

        for video in pending_videos:
            try:
                # Update status to queued
                await db.update_status(video["id"], "queued")

                # Update message caption and add Edit/Cancel button
                keyboard = [[InlineKeyboardButton("🔄 Edit/Cancel", callback_data=f"mod_edit_{video['id']}")]]
                reply_markup = InlineKeyboardMarkup(keyboard)

                # Get the original caption
                if video['is_anonymous']:
                    caption_base = t("caption_anonymous_user", "Video from anonymous user")
                else:
                    username = video["username"]
                    if username and not username.startswith("@"):
                        username = f"@{username}"
                    caption_base = f"Video from user {username}"

                await context.bot.edit_message_caption(
                    chat_id=config.MODERATION_GROUP_ID,
                    message_id=video["moderation_message_id"],
                    caption=f"{caption_base}\n\n✅ Video is queued for publication",
                    reply_markup=reply_markup
                )

                # Notify user
                try:
                    await context.bot.send_message(
                        chat_id=video["user_id"],
                        text=t("video_approved_queued", "Your video has been approved and added to the publication queue.")
                    )
                except TelegramError as e:
                    logger.error(f"Failed to notify user {video['user_id']}: {e}")

                approved_count += 1
                logger.info(f"Video {video['id']} approved via /a command")

            except TelegramError as e:
                logger.error(f"Error approving video {video['id']}: {e}")
                failed_count += 1

        # Send summary
        if failed_count > 0:
            summary = t("approve_all_summary_with_failures",
                       "✅ Approved {approved_count} video(s)\n❌ Failed to approve {failed_count} video(s)",
                       approved_count=approved_count, failed_count=failed_count)
        else:
            summary = t("approve_all_summary",
                       "✅ Approved {approved_count} video(s)",
                       approved_count=approved_count)

        await update.message.reply_text(summary)
        logger.info(f"/a command executed: {approved_count} approved, {failed_count} failed")

    except Exception as e:
        logger.error(f"Error in approve_all_command: {e}")
        await update.message.reply_text(f"❌ Error approving videos: {str(e)}")


async def blacklist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /b command - blacklist management."""
    # Only work in moderation group
    if update.message.chat_id != config.MODERATION_GROUP_ID:
        return

    # Check if user is moderator
    if not is_moderator(update.message.from_user.id, update.message.chat_id):
        await update.message.reply_text(t("unauthorized_command", "❌ You are not authorized to use this command."))
        return

    args = context.args if context.args else []

    try:
        # /b - Display blacklist
        if len(args) == 0:
            blacklist = await db.get_blacklist()
            if not blacklist:
                await update.message.reply_text(t("blacklist_empty", "📋 Blacklist is empty."))
                return

            # Format blacklist
            message_lines = [t("blacklist_header", "📋 *Blacklisted Users:*\n")]
            for entry in blacklist:
                user_info = f"ID: `{entry['user_id']}`"
                if entry['username']:
                    user_info += f" (@{entry['username']})"
                if entry['reason']:
                    user_info += f"\n   Reason: {entry['reason']}"
                added_at = entry['added_at'][:16] if entry['added_at'] else "Unknown"
                user_info += f"\n   Added: {added_at}"
                message_lines.append(user_info)

            message = "\n\n".join(message_lines)
            await update.message.reply_text(message, parse_mode='Markdown')
            logger.info(f"Blacklist displayed by moderator {update.message.from_user.id}")

        # /b clear all - Clear entire blacklist (with confirmation)
        elif len(args) == 2 and args[0].lower() == "clear" and args[1].lower() == "all":
            # Store confirmation state in context.user_data
            context.user_data['pending_blacklist_clear'] = True

            keyboard = [
                [
                    InlineKeyboardButton(t("button_confirm", "✅ Confirm"), callback_data="blacklist_clear_confirm"),
                    InlineKeyboardButton(t("button_cancel", "❌ Cancel"), callback_data="blacklist_clear_cancel")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(
                t("blacklist_clear_all_confirm",
                  "⚠️ *WARNING*: This will remove ALL users from the blacklist.\n\nAre you sure?"),
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )

        # /b clear <user_id> - Remove user from blacklist
        elif len(args) == 2 and args[0].lower() == "clear":
            try:
                user_id = int(args[1])
                was_blacklisted = await db.remove_from_blacklist(user_id)

                if was_blacklisted:
                    await update.message.reply_text(
                        t("blacklist_user_removed", "✅ User `{user_id}` removed from blacklist.", user_id=user_id),
                        parse_mode='Markdown'
                    )
                    logger.info(f"User {user_id} removed from blacklist by moderator {update.message.from_user.id}")
                else:
                    await update.message.reply_text(
                        t("blacklist_user_not_found", "ℹ️ User `{user_id}` was not in the blacklist.", user_id=user_id),
                        parse_mode='Markdown'
                    )
            except ValueError:
                await update.message.reply_text(
                    t("blacklist_invalid_user_id", "❌ Invalid user ID. Please provide a numeric user ID.")
                )

        # /b <user_id> [reason] - Add user to blacklist
        elif len(args) >= 1:
            try:
                user_id = int(args[0])
                reason = " ".join(args[1:]) if len(args) > 1 else None

                # Check if already blacklisted
                already_blacklisted = await db.is_blacklisted(user_id)

                await db.add_to_blacklist(
                    user_id=user_id,
                    added_by=update.message.from_user.id,
                    username=None,  # We don't have username info here
                    reason=reason
                )

                if already_blacklisted:
                    await update.message.reply_text(
                        t("blacklist_user_updated", "✅ User `{user_id}` blacklist entry updated.", user_id=user_id),
                        parse_mode='Markdown'
                    )
                else:
                    await update.message.reply_text(
                        t("blacklist_user_added", "✅ User `{user_id}` added to blacklist.", user_id=user_id),
                        parse_mode='Markdown'
                    )

                logger.info(f"User {user_id} added to blacklist by moderator {update.message.from_user.id}")

            except ValueError:
                await update.message.reply_text(
                    t("blacklist_invalid_user_id", "❌ Invalid user ID. Please provide a numeric user ID.")
                )

        else:
            # Invalid command syntax
            await update.message.reply_text(
                t("blacklist_usage",
                  "❌ Invalid syntax.\n\n"
                  "*Usage:*\n"
                  "`/b` - Show blacklist\n"
                  "`/b <user_id>` - Add user\n"
                  "`/b clear <user_id>` - Remove user\n"
                  "`/b clear all` - Clear all"),
                parse_mode='Markdown'
            )

    except Exception as e:
        logger.error(f"Error in blacklist_command: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")


async def handle_blacklist_clear_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle blacklist clear all confirmation buttons."""
    query = update.callback_query

    # CRITICAL SECURITY CHECKS
    if not is_moderator(query.from_user.id, query.message.chat_id):
        await query.answer(t("error_unauthorized_action", "You are not authorized to perform this action."), show_alert=True)
        return

    await query.answer()

    data = query.data

    if data == "blacklist_clear_confirm":
        # Check if confirmation is pending
        if not context.user_data.get('pending_blacklist_clear'):
            await query.message.edit_text("⚠️ This confirmation has expired. Please run the command again.")
            return

        # Clear the blacklist
        count = await db.clear_blacklist()
        context.user_data['pending_blacklist_clear'] = False

        await query.message.edit_text(
            t("blacklist_cleared", "✅ Blacklist cleared. Removed {count} user(s).", count=count)
        )
        logger.info(f"Blacklist cleared by moderator {query.from_user.id}, removed {count} users")

    elif data == "blacklist_clear_cancel":
        context.user_data['pending_blacklist_clear'] = False
        await query.message.edit_text(
            t("blacklist_clear_cancelled", "❌ Blacklist clear cancelled.")
        )


async def handle_non_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle non-video messages."""
    if update.message.chat.type == "private":
        await update.message.reply_text(t("send_video_prompt", "Please send a video file"))


async def post_init(application: Application):
    """Initialize database and scheduler after bot starts."""
    global db, scheduler

    # Initialize database
    db = Database(config.DATABASE_PATH)
    await db.connect()

    # Initialize scheduler
    scheduler = AsyncIOScheduler(timezone=config.TIMEZONE)

    # Schedule queue publication based on config interval
    scheduler.add_job(
        publish_from_queue,
        'interval',
        minutes=config.PUBLISH_INTERVAL_MINUTES,
        args=[application],
        id="queue_publisher",
        replace_existing=True
    )
    logger.info(f"Queue publisher scheduled to run every {config.PUBLISH_INTERVAL_MINUTES} minute(s)")

    # Schedule check for scheduled videos (every minute)
    scheduler.add_job(
        check_scheduled_videos,
        CronTrigger(minute="*", timezone=config.TIMEZONE),
        args=[application],
        id="scheduled_checker",
        replace_existing=True
    )

    scheduler.start()
    logger.info(f"Scheduler started - Publishing window: {config.PUBLISH_HOURS_START}:00-{config.PUBLISH_HOURS_END}:00 {config.TIMEZONE_STR}")


async def post_shutdown(application: Application):
    """Cleanup on shutdown."""
    global db, scheduler

    if scheduler:
        scheduler.shutdown()
        logger.info("Scheduler stopped")

    if db:
        await db.close()


def main():
    """Start the bot."""
    # Create application
    application = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # Register handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("a", approve_all_command))
    application.add_handler(CommandHandler("b", blacklist_command))
    application.add_handler(MessageHandler(filters.VIDEO & filters.ChatType.PRIVATE, handle_video))
    application.add_handler(MessageHandler(filters.ChatType.PRIVATE & ~filters.VIDEO & ~filters.COMMAND, handle_non_video))
    application.add_handler(CallbackQueryHandler(handle_publication_choice, pattern=r"^pub_"))
    application.add_handler(CallbackQueryHandler(handle_moderation_action, pattern=r"^mod_"))
    # Schedule handlers - order matters, most specific first
    application.add_handler(CallbackQueryHandler(handle_schedule_menu, pattern=r"^schedmenu_"))
    application.add_handler(CallbackQueryHandler(handle_schedule_date, pattern=r"^scheddate_"))
    application.add_handler(CallbackQueryHandler(handle_schedule_time, pattern=r"^schedtime_"))
    application.add_handler(CallbackQueryHandler(handle_schedule_time, pattern=r"^schedback_"))
    application.add_handler(CallbackQueryHandler(handle_schedule_time, pattern=r"^sched_"))
    # Blacklist handlers
    application.add_handler(CallbackQueryHandler(handle_blacklist_clear_confirmation, pattern=r"^blacklist_clear_"))

    # Start bot
    logger.info("Bot starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    import asyncio
    main()
