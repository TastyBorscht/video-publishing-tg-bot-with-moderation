# Video Publisher Bot

A Telegram bot for managing video submissions with moderation workflow and automated publishing.

## Features

- **User Submission**: Users send videos and choose public or anonymous publication
- **Moderation System**: Moderators can approve, reject, schedule, or immediately publish videos
- **Queue Management**: FIFO queue with hourly publication (08:00-23:00 Moscow time)
- **Scheduled Publishing**: Schedule videos for specific date/time
- **Security**: Dual authorization checks (user ID + chat ID verification)
- **Error Handling**: Retry logic, timeout handling, and comprehensive edge case management

## Security Features

✅ All credentials stored in `.env` file
✅ SQL injection prevention with parameterized queries
✅ Chat ID verification to prevent forwarded message exploitation
✅ Moderator authorization with dual checks
✅ `.gitignore` configured to prevent credential leaks

## Setup

### 1. Prerequisites

- Python 3.9+
- Telegram Bot Token (from [@BotFather](https://t.me/BotFather))
- Moderation group (supergroup)
- Target channel for publishing

### 2. Installation

```bash
# Clone or download the project
cd publisher_bot

# Create virtual environment
python -m venv venv

# Activate virtual environment
# On Windows:
venv\Scripts\activate
# On Linux/Mac:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Configuration

Create a `.env` file in the project root (use `.env.example` as template):

```env
# Bot Configuration
BOT_TOKEN=your_bot_token_here

# Chat IDs (use negative values for groups/channels)
MODERATION_GROUP_ID=-1001234567890
TARGET_CHANNEL_ID=-1009876543210

# Moderator User IDs (comma-separated)
MODERATOR_IDS=123456789,987654321

# Timezone and Publishing Schedule
TIMEZONE=Europe/Moscow
PUBLISH_HOURS_START=8
PUBLISH_HOURS_END=23
PUBLISH_INTERVAL_MINUTES=60

# Database
DATABASE_PATH=bot_database.db
```

### 4. Getting Chat IDs

To get chat IDs, you can:

1. **For your user ID**: Send a message to [@userinfobot](https://t.me/userinfobot)
2. **For group/channel IDs**:
   - Add the bot to the group/channel as admin
   - Forward a message from the group/channel to [@userinfobot](https://t.me/userinfobot)
   - Or use this code snippet temporarily in your bot:

   ```python
   async def get_chat_id(update: Update, context):
       await update.message.reply_text(f"Chat ID: {update.message.chat_id}")
   ```

### 5. Bot Permissions

Make sure your bot has these permissions:

**In Moderation Group:**
- Read messages
- Send messages
- Delete messages
- Edit messages

**In Target Channel:**
- Post messages

### 6. Run the Bot

```bash
python bot.py
```

## Usage

### For Users

1. Start a chat with the bot
2. Send a video
3. Choose "Publish publicly" or "Publish anonymously"
4. Wait for moderation decision

### For Moderators

In the moderation group, you'll see submitted videos with 4 buttons:

- **Approve**: Add to publication queue (hourly, 08:00-23:00)
- **Reject**: Decline the video (user notified)
- **Schedule**: Set specific date/time for publication (Note: Currently requires manual implementation of date picker)
- **Publish now**: Immediately publish to channel

## Workflow

```
User submits video
    ↓
Choose public/anonymous (60s timeout)
    ↓
Sent to moderation group
    ↓
Moderator decision:
    ├─ Approve → Queue (hourly publishing)
    ├─ Reject → Delete + notify user
    ├─ Schedule → Publish at specific time
    └─ Publish now → Immediate publication
```

## Database Schema

```sql
Table: videos
- id: Primary key
- file_id: Telegram file_id
- user_id: Submitter's Telegram ID
- username: User's @username or first_name
- is_anonymous: Boolean flag
- status: pending/queued/scheduled/published/rejected/failed
- scheduled_time: For scheduled videos
- moderation_message_id: Message in moderation group
- user_message_id: For timeout tracking
- created_at: Submission timestamp
- published_at: Publication timestamp
- rejected_at: Rejection timestamp
```

## Error Handling

- **Timeout**: Videos with no response in 60s are deleted
- **Retries**: 3 attempts with 30s delay for channel publishing
- **Missing videos**: Caught and logged, status updated to 'failed'
- **Duplicate actions**: Prevented by status checking
- **Unauthorized access**: Blocked with user notification

## Publishing Schedule

- **Queue**: One video per hour from 08:00 to 23:00 Moscow time
- **Scheduled**: Exact date/time specified by moderator
- **Immediate**: Instant publication bypassing queue
- **Ordering**: FIFO based on `created_at` timestamp

## Logs

The bot logs all important events:
- Video submissions
- Moderation actions
- Publication success/failures
- Errors and retries

Check console output or redirect to a log file:

```bash
python bot.py 2>&1 | tee bot.log
```

## Notes

- All database records are preserved (not deleted) for history tracking
- Video file_ids are stored, not the actual files
- If Telegram deletes a video, publication will fail gracefully
- Bot restarts reload scheduled jobs from database

## TODO / Future Improvements

- [ ] Implement interactive date/time picker for scheduling (telegram-calendar library)
- [ ] Add admin commands for queue management
- [ ] Statistics dashboard
- [ ] Persistent job store for APScheduler
- [ ] Database migrations system
- [ ] Unit tests
- [ ] Docker containerization

## Troubleshooting

**Bot doesn't respond to videos:**
- Check bot is running
- Verify BOT_TOKEN in .env
- Ensure you're in private chat

**Moderation buttons don't work:**
- Verify MODERATOR_IDS in .env
- Check MODERATION_GROUP_ID matches your group
- Ensure bot has admin rights in group

**Videos not publishing:**
- Check TARGET_CHANNEL_ID in .env
- Verify bot is admin in target channel
- Check logs for errors

## License

This project is provided as-is for educational and commercial use.
