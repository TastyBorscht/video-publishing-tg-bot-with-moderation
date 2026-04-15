"""
Localization module for the bot.
Provides translation functionality with fallback to default messages.
"""
import json
import logging
from pathlib import Path
from typing import Optional, Dict

logger = logging.getLogger(__name__)


class Localization:
    def __init__(self, localization_file: str = "localization.json"):
        self.localization_file = localization_file
        self.translations: Dict[str, str] = {}
        self.load_translations()

    def load_translations(self):
        """Load translations from JSON file."""
        try:
            file_path = Path(self.localization_file)
            if file_path.exists():
                with open(file_path, 'r', encoding='utf-8') as f:
                    self.translations = json.load(f)
                logger.info(f"Loaded {len(self.translations)} translations from {self.localization_file}")
            else:
                logger.warning(f"Localization file {self.localization_file} not found. Using default messages.")
                self.translations = {}
        except Exception as e:
            logger.error(f"Error loading localization file: {e}")
            self.translations = {}

    def reload(self):
        """Reload translations from file."""
        self.load_translations()

    def get(self, key: str, default: Optional[str] = None, **kwargs) -> str:
        """
        Get translated message by key.

        Args:
            key: Message key/identifier
            default: Default message if translation not found
            **kwargs: Format parameters for the message

        Returns:
            Translated message or default message, with format parameters applied
        """
        # Get message from translations or use default
        message = self.translations.get(key, default if default is not None else key)

        # Apply format parameters if provided
        if kwargs:
            try:
                message = message.format(**kwargs)
            except KeyError as e:
                logger.warning(f"Missing format parameter {e} for key '{key}'")

        return message

    def t(self, key: str, default: Optional[str] = None, **kwargs) -> str:
        """Alias for get() - shorter syntax."""
        return self.get(key, default, **kwargs)


# Global localization instance
_localization: Optional[Localization] = None


def init_localization(localization_file: str = "localization.json"):
    """Initialize global localization instance."""
    global _localization
    _localization = Localization(localization_file)
    return _localization


def get_localization() -> Localization:
    """Get global localization instance."""
    global _localization
    if _localization is None:
        _localization = Localization()
    return _localization


def t(key: str, default: Optional[str] = None, **kwargs) -> str:
    """
    Shorthand function for translation.

    Usage:
        t("welcome_message", "Welcome to the bot!")
        t("video_approved", "Video {video_id} approved", video_id=123)
    """
    return get_localization().get(key, default, **kwargs)
