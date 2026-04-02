import logging
from typing import Optional

from aiogram import F, Router, types
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.inline.admin_keyboards import (
    get_admin_referral_settings_keyboard,
    get_withdraw_request_admin_keyboard,
)
from bot.middlewares.i18n import JsonI18n
from bot.states.admin_states import AdminStates
from config.settings import Settings
from db.dal import referral_finance_dal, user_dal

router = Router(name="admin_referral_finance_router")


@router.callback_query(F.data == "admin_action:referral_settings")
async def referral_settings_panel(
    callback: types.CallbackQuery,
    settings: Settings,
    i18n_data: dict,
    session: AsyncSession,
):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs) if i18n else key

    percent = await referral_finance_dal.get_referral_commission_percent(session)
    pending_count = await referral_finance_dal.get_pending_withdrawal_count(session)
    await callback.message.edit_text(
        _("admin_referral_settings_text", percent=percent, pending_count=pending_count),
        reply_markup=get_admin_referral_settings_keyboard(i18n, current_lang),
    )
    await callback.answer()


@router.callback_query(F.data == "admin_referral:set_percent_prompt")
async def referral_percent_prompt(
    callback: types.CallbackQuery,
    state: FSMContext,
    settings: Settings,
    i18n_data: dict,
):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs) if i18n else key

    await state.set_state(AdminStates.waiting_for_referral_commission_percent)
    await callback.message.answer(_("admin_referral_set_percent_prompt"))
    await callback.answer()


@router.message(AdminStates.waiting_for_referral_commission_percent, F.text)
async def save_referral_percent(
    message: types.Message,
    state: FSMContext,
    settings: Settings,
    i18n_data: dict,
    session: AsyncSession,
):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs) if i18n else key

    try:
        percent = int((message.text or "").strip())
    except ValueError:
        await message.answer(_("admin_referral_percent_invalid"))
        return

    if percent < 0 or percent > 100:
        await message.answer(_("admin_referral_percent_invalid"))
        return

    await referral_finance_dal.set_referral_commission_percent(session, percent)
    await session.commit()
    await state.clear()
    await message.answer(_("admin_referral_percent_saved", percent=percent))


@router.callback_query(F.data == "admin_action:withdraw_requests")
async def list_withdraw_requests(
    callback: types.CallbackQuery,
    settings: Settings,
    i18n_data: dict,
    session: AsyncSession,
):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs) if i18n else key

    requests = await referral_finance_dal.list_pending_withdrawal_requests(session)
    if not requests:
        await callback.message.edit_text(
            _("admin_withdraw_requests_empty"),
            reply_markup=get_admin_referral_settings_keyboard(i18n, current_lang),
        )
        await callback.answer()
        return

    lines = [_("admin_withdraw_requests_title")]
    for request in requests:
        user = await user_dal.get_user_by_id(session, request.user_id)
        user_display = user.username and f"@{user.username}" or str(request.user_id)
        lines.append(
            _("admin_withdraw_request_line",
              request_id=request.request_id,
              user_display=user_display,
              amount=request.amount_rub)
        )

    first_request = requests[0]
    await callback.message.edit_text(
        "\n".join(lines) + "\n\n" + _("admin_withdraw_request_details",
                                     request_id=first_request.request_id,
                                     user_id=first_request.user_id,
                                     amount=first_request.amount_rub,
                                     details=first_request.payment_details),
        reply_markup=get_withdraw_request_admin_keyboard(first_request.request_id, i18n, current_lang),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_referral:withdraw:"))
async def process_withdraw_request_action(
    callback: types.CallbackQuery,
    settings: Settings,
    i18n_data: dict,
    session: AsyncSession,
):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs) if i18n else key

    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer(_("error_try_again"), show_alert=True)
        return

    action = parts[2]
    request_id = int(parts[3])
    if action == "approve":
        request = await referral_finance_dal.approve_withdrawal_request(
            session, request_id, callback.from_user.id
        )
        status_key = "withdraw_request_approved_user"
        admin_key = "admin_withdraw_request_approved"
    else:
        request = await referral_finance_dal.reject_withdrawal_request(
            session, request_id, callback.from_user.id
        )
        status_key = "withdraw_request_rejected_user"
        admin_key = "admin_withdraw_request_rejected"

    if not request:
        await callback.answer(_("error_try_again"), show_alert=True)
        return

    await session.commit()

    user = await user_dal.get_user_by_id(session, request.user_id)
    if user:
        user_lang = user.language_code or settings.DEFAULT_LANGUAGE
        _u = lambda key, **kwargs: i18n.gettext(user_lang, key, **kwargs)
        try:
            await callback.bot.send_message(
                user.user_id,
                _u(status_key, amount=request.amount_rub),
            )
        except Exception as exc:
            logging.error("Failed to notify user %s about withdrawal request %s: %s", user.user_id, request.request_id, exc)

    await callback.message.edit_text(
        _(admin_key, request_id=request.request_id),
        reply_markup=get_admin_referral_settings_keyboard(i18n, current_lang),
    )
    await callback.answer()
