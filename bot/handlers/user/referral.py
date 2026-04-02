import logging
from aiogram import Router, F, types, Bot
from aiogram.fsm.context import FSMContext
from typing import Optional, Union
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import Settings
from bot.services.referral_service import ReferralService
from bot.states.user_states import UserReferralStates

from bot.keyboards.inline.user_keyboards import get_back_to_main_menu_markup
from bot.middlewares.i18n import JsonI18n
from bot.utils.screen_media import send_screen
from db.dal import referral_finance_dal

router = Router(name="user_referral_router")


async def referral_command_handler(event: Union[types.Message,
                                                types.CallbackQuery],
                                   settings: Settings, i18n_data: dict,
                                   referral_service: ReferralService, bot: Bot,
                                   session: AsyncSession):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")

    target_message_obj = event.message if isinstance(
        event, types.CallbackQuery) else event
    if not target_message_obj:
        logging.error(
            "Target message is None in referral_command_handler (possibly from callback without message)."
        )
        if isinstance(event, types.CallbackQuery):
            await event.answer("Error displaying referral info.",
                               show_alert=True)
        return

    if not i18n or not referral_service:
        logging.error(
            "Dependencies (i18n or ReferralService) missing in referral_command_handler"
        )
        await target_message_obj.answer(
            "Service error. Please try again later.")
        if isinstance(event, types.CallbackQuery): await event.answer()
        return

    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    if not settings.REFERRAL_ENABLED:
        await target_message_obj.answer(
            _("referral_no_bonuses_configured"),
            reply_markup=get_back_to_main_menu_markup(current_lang, i18n),
        )
        if isinstance(event, types.CallbackQuery):
            await event.answer()
        return

    try:
        bot_info = await bot.get_me()
        bot_username = bot_info.username
    except Exception as e_bot_info:
        logging.error(
            f"Failed to get bot info for referral link: {e_bot_info}")
        await target_message_obj.answer(_("error_generating_referral_link"))
        if isinstance(event, types.CallbackQuery): await event.answer()
        return

    if not bot_username:
        logging.error("Bot username is None, cannot generate referral link.")
        await target_message_obj.answer(_("error_generating_referral_link"))
        if isinstance(event, types.CallbackQuery): await event.answer()
        return

    inviter_user_id = event.from_user.id
    referral_link = await referral_service.generate_referral_link(
        session, bot_username, inviter_user_id)

    if not referral_link:
        logging.error(
            "Failed to generate referral link for user %s (probably missing DB record).",
            inviter_user_id,
        )
        await target_message_obj.answer(_("error_generating_referral_link"))
        if isinstance(event, types.CallbackQuery):
            await event.answer()
        return

    referral_stats = await referral_service.get_referral_stats(session, inviter_user_id)
    recent_transactions = await referral_finance_dal.get_recent_balance_transactions(
        session,
        inviter_user_id,
        limit=5,
    )
    history_lines = []
    for tx in recent_transactions:
        amount_sign = "+" if tx.amount_rub >= 0 else ""
        history_lines.append(
            _("referral_balance_history_line",
              amount=f"{amount_sign}{tx.amount_rub:.2f}",
              type=tx.transaction_type,
              status=tx.status)
        )
    history_text = "\n".join(history_lines) if history_lines else _("referral_balance_history_empty")

    text = _("referral_program_info_new",
             referral_link=referral_link,
             commission_percent=referral_stats["commission_percent"],
             balance_rub=referral_stats["balance_rub"],
             total_earned_rub=referral_stats["referral_total_earned_rub"],
             balance_history=history_text,
             invited_count=referral_stats["invited_count"],
             purchased_count=referral_stats["purchased_count"])

    from bot.keyboards.inline.user_keyboards import get_referral_link_keyboard
    reply_markup_val = get_referral_link_keyboard(current_lang, i18n)

    await send_screen(
        event,
        settings,
        "referral",
        text,
        reply_markup=reply_markup_val,
        disable_web_page_preview=True,
        is_edit=isinstance(event, types.CallbackQuery),
    )


@router.callback_query(F.data.startswith("referral_action:"))
async def referral_action_handler(callback: types.CallbackQuery, settings: Settings, 
                                 i18n_data: dict, referral_service: ReferralService, 
                                 bot: Bot, session: AsyncSession, state: FSMContext):
    action = callback.data.split(":")[1]
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n = i18n_data.get("i18n_instance")
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs)

    if action == "share_message":
        if not settings.REFERRAL_ENABLED:
            await callback.answer(_("referral_no_bonuses_configured"), show_alert=True)
            return
        try:
            bot_info = await bot.get_me()
            bot_username = bot_info.username
            if not bot_username:
                await callback.answer("Ошибка получения имени бота", show_alert=True)
                return

            inviter_user_id = callback.from_user.id
            referral_link = await referral_service.generate_referral_link(
                session, bot_username, inviter_user_id)

            if not referral_link:
                logging.error(
                    "Failed to generate referral link for user %s via inline button.",
                    inviter_user_id,
                )
                await callback.answer(_("error_generating_referral_link"), show_alert=True)
                return
            
            friend_message = _("referral_friend_message", referral_link=referral_link)
            
            await callback.message.answer(
                friend_message,
                disable_web_page_preview=True
            )
            
        except Exception as e:
            logging.error(f"Error in referral share message: {e}")
            await callback.answer("Произошла ошибка", show_alert=True)
    elif action == "withdraw":
        await state.set_state(UserReferralStates.waiting_for_withdraw_request)
        await callback.message.answer(
            _("referral_withdraw_prompt"),
            reply_markup=get_back_to_main_menu_markup(current_lang, i18n, callback_data="main_action:referral"),
        )
        
    await callback.answer()


@router.message(UserReferralStates.waiting_for_withdraw_request, F.text)
async def process_withdraw_request(
    message: types.Message,
    state: FSMContext,
    settings: Settings,
    i18n_data: dict,
    session: AsyncSession,
):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs) if i18n else key

    raw_text = (message.text or "").strip()
    amount_part, _, details_part = raw_text.partition("\n")
    if not amount_part or not details_part.strip():
        await message.answer(_("referral_withdraw_invalid_format"))
        return

    try:
        amount_rub = round(float(amount_part.replace(",", ".")), 2)
    except ValueError:
        await message.answer(_("referral_withdraw_invalid_format"))
        return

    request = await referral_finance_dal.create_withdrawal_request(
        session,
        message.from_user.id,
        amount_rub,
        details_part.strip(),
    )
    if not request:
        await message.answer(_("referral_withdraw_insufficient_balance"))
        return

    await session.commit()
    await state.clear()
    await message.answer(_("referral_withdraw_created", amount=amount_rub))
