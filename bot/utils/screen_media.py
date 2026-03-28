import logging
from pathlib import Path
from typing import Optional, Union

from aiogram import Bot, types
from aiogram.types import FSInputFile, InlineKeyboardMarkup

from config.settings import Settings

SCREEN_MEDIA_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
MAX_CAPTION_LENGTH = 1024


def get_screen_media_path(settings: Settings, screen_key: str) -> Optional[Path]:
    media_dir = Path(settings.SCREEN_MEDIA_DIR)
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
            await target_message.answer_photo(
                photo=media,
                caption=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
            )
        else:
            await target_message.answer_photo(photo=media)
            await target_message.answer(
                text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
                disable_web_page_preview=disable_web_page_preview,
            )
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
            await target_message.edit_text(
                text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
                disable_web_page_preview=disable_web_page_preview,
            )
        except Exception:
            if bot:
                await bot.send_message(
                    chat_id=target_message.chat.id,
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode,
                    disable_web_page_preview=disable_web_page_preview,
                )
            else:
                await target_message.answer(
                    text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode,
                    disable_web_page_preview=disable_web_page_preview,
                )
        finally:
            try:
                await event.answer()
            except Exception as exc:
                logging.debug("Suppressed exception in bot/utils/screen_media.py: %s", exc)
        return

    await target_message.answer(
        text,
        reply_markup=reply_markup,
        parse_mode=parse_mode,
        disable_web_page_preview=disable_web_page_preview,
    )
    if isinstance(event, types.CallbackQuery):
        try:
            await event.answer()
        except Exception as exc:
            logging.debug("Suppressed exception in bot/utils/screen_media.py: %s", exc)
