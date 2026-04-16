# Docker Setup for Publisher Bot

This guide explains how to run the Publisher Bot using Docker Compose.

## Prerequisites

- Docker Engine 20.10+
- Docker Compose 2.0+

## Quick Start

1. **Prepare configuration files** in the same directory as `docker-compose.yml`:
   ```
   publisher_bot/
   ├── docker-compose.yml
   ├── .env                  # Your bot configuration
   ├── localization.json     # Message translations
   └── data/                 # Will be created automatically for database
   ```

2. **Configure your .env file** with required settings:
   ```bash
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
   PUBLISH_INTERVAL_MINUTES=1

   # Database (optional, default is shown)
   DATABASE_PATH=/app/data/bot_database.db
   ```

3. **Start the bot**:
   ```bash
   docker-compose up -d
   ```

## Commands

### Start the bot
```bash
docker-compose up -d
```

### Stop the bot
```bash
docker-compose down
```

### View logs
```bash
# Follow logs in real-time
docker-compose logs -f

# View last 100 lines
docker-compose logs --tail=100

# View logs for specific time
docker-compose logs --since 1h
```

### Restart the bot
```bash
docker-compose restart
```

### Rebuild after code changes
```bash
docker-compose up -d --build
```

### Check status
```bash
docker-compose ps
```

## File Structure

### Required Files (must be in the same directory as docker-compose.yml)

- **`.env`** - Bot configuration (REQUIRED)
  - Contains bot token, chat IDs, moderator IDs
  - See `.env.example` for template

- **`localization.json`** - Message translations (REQUIRED)
  - Contains localized messages for users
  - Falls back to default messages if keys are missing

### Generated Files

- **`data/`** - Directory for database persistence
  - Created automatically on first run
  - Contains `bot_database.db` (SQLite database)
  - Videos, blacklist, and schedules are stored here

## Configuration Updates

### Updating .env
1. Edit `.env` file
2. Restart the bot:
   ```bash
   docker-compose restart
   ```

### Updating localization.json
1. Edit `localization.json` file
2. Restart the bot:
   ```bash
   docker-compose restart
   ```

## Data Persistence

The bot data is stored in the `./data` directory on your host machine:

- **Database**: `./data/bot_database.db`
- Persists through container restarts and recreations
- **Backup**: Simply copy the `./data` directory

### Backup Database
```bash
# Create backup
cp -r ./data ./data.backup

# Or use timestamp
cp -r ./data ./data.backup.$(date +%Y%m%d_%H%M%S)
```

### Restore Database
```bash
# Stop the bot
docker-compose down

# Restore data
rm -rf ./data
cp -r ./data.backup ./data

# Start the bot
docker-compose up -d
```

## Troubleshooting

### Bot won't start
1. Check logs:
   ```bash
   docker-compose logs
   ```

2. Verify `.env` file exists and has correct values:
   ```bash
   cat .env
   ```

3. Check if required files exist:
   ```bash
   ls -la .env localization.json
   ```

### Database errors
1. Check database file permissions:
   ```bash
   ls -la data/bot_database.db
   ```

2. If database is corrupted, restore from backup or delete to start fresh:
   ```bash
   docker-compose down
   rm -rf data/
   docker-compose up -d
   ```

### Config changes not applying
1. Ensure you restarted the container:
   ```bash
   docker-compose restart
   ```

2. Check if correct .env is being used:
   ```bash
   docker-compose exec publisher_bot cat /app/.env
   ```

### View bot environment
```bash
docker-compose exec publisher_bot env | grep -E "BOT_TOKEN|MODERATION|TARGET|MODERATOR"
```

## Advanced Configuration

### Custom database location
Edit `docker-compose.yml` to change database path:
```yaml
environment:
  - DATABASE_PATH=/app/data/custom_database.db
```

### Resource limits
Add resource limits to `docker-compose.yml`:
```yaml
services:
  publisher_bot:
    # ... other config ...
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 512M
        reservations:
          cpus: '0.25'
          memory: 256M
```

### Custom logging
Modify logging configuration in `docker-compose.yml`:
```yaml
logging:
  driver: "json-file"
  options:
    max-size: "50m"    # Increase log file size
    max-file: "5"      # Keep more log files
```

## Health Check

The bot includes a health check that verifies the database file exists:

```bash
# Check health status
docker-compose ps

# Manually run health check
docker-compose exec publisher_bot python -c "import os; print('OK' if os.path.exists('/app/data/bot_database.db') else 'FAIL')"
```

## Security Notes

- **Never commit `.env` file** - it contains sensitive tokens
- Keep `.env` file readable only by owner:
  ```bash
  chmod 600 .env
  ```
- Regularly backup your database
- Review `localization.json` for any sensitive information before sharing

## Updating the Bot

1. Pull latest code changes
2. Rebuild and restart:
   ```bash
   docker-compose down
   docker-compose up -d --build
   ```

## Production Deployment

For production environments:

1. Use Docker secrets instead of .env for sensitive data
2. Set up log rotation
3. Configure automatic restarts: `restart: always`
4. Set up monitoring and alerts
5. Regular database backups
6. Use a reverse proxy if exposing any ports

## Support

For issues or questions:
- Check logs: `docker-compose logs -f`
- Verify configuration files are correct
- Ensure bot has proper permissions in Telegram groups/channels
