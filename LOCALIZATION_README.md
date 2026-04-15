# Localization System

This bot supports message localization/translation through a simple JSON-based system.

## How It Works

1. **Localization File**: `localization.json` contains all translated messages
2. **Fallback**: If a translation is not found, the default message from the code is used
3. **Format Parameters**: Messages can include placeholders like `{video_id}` that are replaced with actual values

## Usage in Code

The bot uses the `t()` function (short for "translate") to get localized messages:

```python
from localization import t

# Simple message
await update.message.reply_text(t("welcome_message", "Welcome to the bot!"))

# Message with parameters
message = t("video_scheduled",
           "Your video has been scheduled for {scheduled_time}.",
           scheduled_time="2024-01-15 10:00")
```

### Syntax

```python
t(key, default, **kwargs)
```

- **key**: The message identifier in `localization.json`
- **default**: The fallback message if the key is not found
- **kwargs**: Format parameters to replace placeholders in the message

## Adding New Translations

### Step 1: Edit `localization.json`

Add your translation with a unique key:

```json
{
  "my_new_message": "This is my new translated message",
  "message_with_params": "Hello {username}, you have {count} videos"
}
```

### Step 2: Use in Code

```python
# Simple message
t("my_new_message", "Default message if translation not found")

# With parameters
t("message_with_params",
  "Hello {username}, you have {count} videos",
  username="John",
  count=5)
```

## Current Translations

The following messages are currently localized:

### User Messages
- `welcome_message` - Welcome message on /start command
- `send_video_prompt` - Prompt to send a video
- `choose_publication_type` - Publication type selection
- `video_sent_to_moderation` - Confirmation that video was sent
- `video_approved_queued` - Video approved notification
- `video_not_approved` - Video rejected notification
- `video_published` - Video published notification
- `video_scheduled` - Video scheduled notification

### Error Messages
- `unauthorized_action` - Unauthorized action message
- `video_not_found` - Video not found error
- `video_already_processed` - Already processed error
- `video_already_published_or_rejected` - Cannot edit published video

### Command Messages
- `no_pending_videos` - No pending videos message
- `approve_all_summary` - Approval summary
- `approve_all_summary_with_failures` - Approval summary with failures
- `unauthorized_command` - Unauthorized command error

### Button Labels
- `button_publish_publicly` - "Publish publicly"
- `button_publish_anonymously` - "Publish anonymously"
- `button_approve` - "Approve"
- `button_reject` - "Reject"
- `button_schedule` - "Schedule"
- `button_publish_now` - "Publish now"
- `button_edit_cancel` - "Edit/Cancel"
- And more...

## Reloading Translations

To reload translations without restarting the bot:

```python
from localization import get_localization

get_localization().reload()
```

## Example localization.json

```json
{
  "welcome_message": "Добро пожаловать в бот отправки видео!\n\nОтправьте мне видео для публикации.",
  "send_video_prompt": "Пожалуйста, отправьте видеофайл",
  "video_approved_queued": "Ваше видео одобрено и добавлено в очередь публикации.",
  "video_published": "Ваше видео опубликовано.",
  "approve_all_summary": "✅ Одобрено {approved_count} видео"
}
```

## Best Practices

1. **Always provide a default**: Include the default message as the second parameter to `t()`
2. **Use descriptive keys**: Use clear, descriptive keys like `video_approved_queued` instead of `msg1`
3. **Keep messages in sync**: When adding new messages to the code, add them to `localization.json`
4. **Test with missing translations**: The system should gracefully fall back to defaults
5. **Document parameters**: If a message uses parameters, document what they are

## Tips

- The localization file is loaded on bot startup
- If the file is missing, the bot will use all default messages
- Invalid JSON in the localization file will cause the bot to use defaults
- Comments in JSON are supported using `"_comment"` keys (they are ignored)
