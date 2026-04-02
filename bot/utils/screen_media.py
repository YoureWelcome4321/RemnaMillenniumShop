import logging
from pathlib import Path
from typing import Optional, Union

from aiogram import Bot, types
from aiogram.types import FSInputFile, InlineKeyboardMarkup

from config.settings import Settings

SCREEN_MEDIA_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
MAX_CAPTION_LENGTH = 1024
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _resolve_media_dir(settings: Settings) -> Path:
    media_dir = Path(settings.SCREEN_MEDIA_DIR)
    if media_dir.is_absolute():
        return media_dir
    return PROJECT_ROOT / media_dir


def get_screen_media_path(settings: Settings, screen_key: str) -> Optional[Path]:
    media_dir = _resolve_media_dir(settings)
    for extension in SCREEN_MEDIA_EXTENSIONS:
        candidate = media_dir / f"{screen_key}{extension}"
        if candidate.is_file():
            return candidate
    return None


async def send_screen(
    event: Union[types.Message, types.CallbackQuery],
    settings: Settings,
    screen_key: str,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    parse_mode: Optional[str] = None,
    disable_web_page_preview: bool = False,
    is_edit: bool = False,
    bot: Optional[Bot] = None,
) -> None:
    target_message = event.message if isinstance(event, types.CallbackQuery) else event
    if not target_message:
        if isinstance(event, types.CallbackQuery):
            try:
                await event.answer()
            except Exception as exc:
                logging.debug("Suppressed exception in bot/utils/screen_media.py: %s", exc)
        return

    media_path = get_screen_media_path(settings, screen_key)
    if not media_path:
        await _send_text(
            event=event,
            target_message=target_message,
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
            disable_web_page_preview=disable_web_page_preview,
            is_edit=is_edit,
            bot=bot,
        )
        return

    if isinstance(event, types.CallbackQuery) and is_edit:
        try:
            await target_message.delete()
        except Exception as exc:
            logging.debug("Suppressed exception in bot/utils/screen_media.py: %s", exc)

    try:
        media = FSInputFile(media_path)
        if len(text) <= MAX_CAPTION_LENGTH:
            photo_kwargs = {
                "photo": media,
                "caption": text,
                "reply_markup": reply_markup,
            }
            if parse_mode is not None:
                photo_kwargs["parse_mode"] = parse_mode
            await target_message.answer_photo(**photo_kwargs)
        else:
            await target_message.answer_photo(photo=media)
            text_kwargs = {
                "reply_markup": reply_markup,
                "disable_web_page_preview": disable_web_page_preview,
            }
            if parse_mode is not None:
                text_kwargs["parse_mode"] = parse_mode
            await target_message.answer(text, **text_kwargs)
    finally:
        if isinstance(event, types.CallbackQuery):
            try:
                await event.answer()
            except Exception as exc:
                logging.debug("Suppressed exception in bot/utils/screen_media.py: %s", exc)


async def _send_text(
    event: Union[types.Message, types.CallbackQuery],
    target_message: types.Message,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup],
    parse_mode: Optional[str],
    disable_web_page_preview: bool,
    is_edit: bool,
    bot: Optional[Bot],
) -> None:
    if isinstance(event, types.CallbackQuery) and is_edit:
        try:
            edit_kwargs = {
                "reply_markup": reply_markup,
                "disable_web_page_preview": disable_web_page_preview,
            }
            if parse_mode is not None:
                edit_kwargs["parse_mode"] = parse_mode
            await target_message.edit_text(text, **edit_kwargs)
        except Exception:
            if bot:
                send_kwargs = {
                    "chat_id": target_message.chat.id,
                    "text": text,
                    "reply_markup": reply_markup,
                    "disable_web_page_preview": disable_web_page_preview,
                }
                if parse_mode is not None:
                    send_kwargs["parse_mode"] = parse_mode
                await bot.send_message(**send_kwargs)
            else:
                answer_kwargs = {
                    "reply_markup": reply_markup,
                    "disable_web_page_preview": disable_web_page_preview,
                }
                if parse_mode is not None:
                    answer_kwargs["parse_mode"] = parse_mode
                await target_message.answer(text, **answer_kwargs)
        finally:
            try:
                await event.answer()
            except Exception as exc:
                logging.debug("Suppressed exception in bot/utils/screen_media.py: %s", exc)
        return

    answer_kwargs = {
        "reply_markup": reply_markup,
        "disable_web_page_preview": disable_web_page_preview,
    }
    if parse_mode is not None:
        answer_kwargs["parse_mode"] = parse_mode
    await target_message.answer(text, **answer_kwargs)
    if isinstance(event, types.CallbackQuery):
        try:
            await event.answer()
        except Exception as exc:
            logging.debug("Suppressed exception in bot/utils/screen_media.py: %s", exc)
