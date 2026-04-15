"""
Configuration loader for the bot.
Loads all settings from .env file using python-dotenv.
"""
from dotenv import load_dotenv
import os
import pytz
from typing import List

# Load environment variables from .env file
load_dotenv()

# Bot token
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is required in .env file")

# Chat IDs
MODERATION_GROUP_ID = os.getenv("MODERATION_GROUP_ID")
if not MODERATION_GROUP_ID:
    raise ValueError("MODERATION_GROUP_ID is required in .env file")
MODERATION_GROUP_ID = int(MODERATION_GROUP_ID)

TARGET_CHANNEL_ID = os.getenv("TARGET_CHANNEL_ID")
if not TARGET_CHANNEL_ID:
    raise ValueError("TARGET_CHANNEL_ID is required in .env file")
TARGET_CHANNEL_ID = int(TARGET_CHANNEL_ID)

# Moderator IDs
MODERATOR_IDS_STR = os.getenv("MODERATOR_IDS")
if not MODERATOR_IDS_STR:
    raise ValueError("MODERATOR_IDS is required in .env file")
MODERATOR_IDS: List[int] = [int(x.strip()) for x in MODERATOR_IDS_STR.split(",")]

# Timezone and scheduling
TIMEZONE_STR = os.getenv("TIMEZONE", "Europe/Moscow")
TIMEZONE = pytz.timezone(TIMEZONE_STR)
PUBLISH_HOURS_START = int(os.getenv("PUBLISH_HOURS_START", "8"))
PUBLISH_HOURS_END = int(os.getenv("PUBLISH_HOURS_END", "23"))
PUBLISH_INTERVAL_MINUTES = int(os.getenv("PUBLISH_INTERVAL_MINUTES", "60"))

# Database
DATABASE_PATH = os.getenv("DATABASE_PATH", "bot_database.db")

# Constants
SUBMISSION_TIMEOUT_SECONDS = 60
RETRY_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 30
MODERATION_GROUP_NAME = "Control of submitted videos"
