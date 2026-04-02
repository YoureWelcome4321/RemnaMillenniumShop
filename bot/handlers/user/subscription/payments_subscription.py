import logging
import math
from typing import Optional

from aiogram import F, Router, types
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.inline.user_keyboards import get_payment_method_keyboard
from bot.middlewares.i18n import JsonI18n
from bot.keyboards.inline.user_keyboards import get_connect_and_main_keyboard
from bot.utils.config_link import prepare_config_links
from config.settings import Settings
from db.dal import payment_dal, referral_finance_dal, user_dal

router = Router(name="user_subscription_payments_selection_router")


async def resolve_fiat_offer_price_for_user(
    session: AsyncSession,
    settings: Settings,
    user_id: int,
    months: float,
    sale_mode: str,
    promo_code_service=None,
) -> Optional[float]:
    """Resolve offer price server-side to prevent callback payload tampering."""
    price_source = (
        getattr(settings, "traffic_packages", {}) or {}
        if sale_mode == "traffic"
        else (settings.subscription_options or {})
    )
    base_price = price_source.get(months)
    if base_price is None:
        return None

    resolved_price = float(base_price)
    if promo_code_service:
        active_discount_info = await promo_code_service.get_user_active_discount(session, user_id)
        if active_discount_info:
            discount_pct, _ = active_discount_info
            resolved_price, _ = promo_code_service.calculate_discounted_price(
                resolved_price,
                discount_pct,
            )
    return resolved_price


@router.callback_query(F.data.startswith("subscribe_period:"))
async def select_subscription_period_callback_handler(
    callback: types.CallbackQuery,
    settings: Settings,
    i18n_data: dict,
    session: AsyncSession,
    promo_code_service=None,  # Injected from dispatcher
):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    get_text = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs) if i18n else key

    if not i18n or not callback.message:
        try:
            await callback.answer(get_text("error_occurred_try_again"), show_alert=True)
        except Exception as exc:
            logging.debug("Suppressed exception in bot/handlers/user/subscription/payments_subscription.py: %s", exc)
        return

    traffic_packages = getattr(settings, "traffic_packages", {}) or {}
    stars_traffic_packages = getattr(settings, "stars_traffic_packages", {}) or {}
    traffic_mode = bool(getattr(settings, "traffic_sale_mode", False) or stars_traffic_packages)
    try:
        months = float(callback.data.split(":")[-1])
    except (ValueError, IndexError):
        logging.error(f"Invalid subscription period in callback_data: {callback.data}")
        try:
            await callback.answer(get_text("error_try_again"), show_alert=True)
        except Exception as exc:
            logging.debug("Suppressed exception in bot/handlers/user/subscription/payments_subscription.py: %s", exc)
        return

    price_source = traffic_packages if traffic_mode else settings.subscription_options
    stars_price_source = stars_traffic_packages if traffic_mode else settings.stars_subscription_options

    price_rub = price_source.get(months)
    stars_price = stars_price_source.get(months)
    currency_symbol_val = "RUB"

    # Check for active discount and apply if exists
    discount_text = ""
    if promo_code_service and (price_rub is not None or stars_price is not None):
        active_discount_info = await promo_code_service.get_user_active_discount(
            session, callback.from_user.id
        )

        if active_discount_info:
            discount_pct, promo_code = active_discount_info
            if price_rub is not None:
                original_price_rub = price_rub
                price_rub, discount_amt = promo_code_service.calculate_discounted_price(
                    price_rub, discount_pct
                )
                discount_text = get_text(
                    "active_discount_notice",
                    code=promo_code,
                    discount_pct=discount_pct,
                    original_price=original_price_rub,
                    discounted_price=price_rub,
                    discount_amount=discount_amt,
                    currency_symbol=currency_symbol_val,
                )
            if stars_price is not None:
                original_stars_price = stars_price
                discounted_stars_price, _ = promo_code_service.calculate_discounted_price(
                    float(stars_price), discount_pct
                )
                discounted_stars_price = math.ceil(discounted_stars_price)
                stars_price = discounted_stars_price
                if not discount_text:
                    discount_amt = original_stars_price - discounted_stars_price
                    discount_text = get_text(
                        "active_discount_notice",
                        code=promo_code,
                        discount_pct=discount_pct,
                        original_price=original_stars_price,
                        discounted_price=discounted_stars_price,
                        discount_amount=discount_amt,
                        currency_symbol="⭐",
                    )

    if price_rub is None:
        if traffic_mode and not price_source and stars_price is not None:
            currency_methods_enabled = any(
                [
                    settings.FREEKASSA_ENABLED,
                    settings.PLATEGA_ENABLED,
                    settings.SEVERPAY_ENABLED,
                    settings.YOOKASSA_ENABLED,
                    settings.CRYPTOPAY_ENABLED,
                ]
            )
            if currency_methods_enabled:
                logging.error(
                    "Currency price missing for traffic option %s while fiat providers are enabled.",
                    months,
                )
                try:
                    await callback.answer(get_text("error_try_again"), show_alert=True)
                except Exception as exc:
                    logging.debug("Suppressed exception in bot/handlers/user/subscription/payments_subscription.py: %s", exc)
                return
            price_rub = 0.0
            currency_symbol_val = "⭐"
        else:
            logging.error(
                f"Price not found for option {months} using {'traffic_packages' if traffic_mode else 'subscription_options'}."
            )
            try:
                await callback.answer(get_text("error_try_again"), show_alert=True)
            except Exception as exc:
                logging.debug("Suppressed exception in bot/handlers/user/subscription/payments_subscription.py: %s", exc)
            return

    text_content = get_text("choose_payment_method_traffic") if traffic_mode else get_text("choose_payment_method")
    if discount_text:
        text_content = f"{discount_text}\n\n{text_content}"

    reply_markup = get_payment_method_keyboard(
        months,
        price_rub,
        stars_price,
        currency_symbol_val,
        current_lang,
        i18n,
        settings,
        sale_mode="traffic" if traffic_mode else "subscription",
    )

    try:
        await callback.message.edit_text(text_content, reply_markup=reply_markup)
    except Exception as e_edit:
        logging.warning(
            f"Edit message for payment method selection failed: {e_edit}. Sending new one."
        )
        await callback.message.answer(text_content, reply_markup=reply_markup)
    try:
        await callback.answer()
    except Exception as exc:
        logging.debug("Suppressed exception in bot/handlers/user/subscription/payments_subscription.py: %s", exc)


@router.callback_query(F.data.startswith("pay_balance:"))
async def pay_with_balance_callback_handler(
    callback: types.CallbackQuery,
    settings: Settings,
    i18n_data: dict,
    session: AsyncSession,
    subscription_service,
    promo_code_service=None,
):
    current_lang = i18n_data.get("current_language", settings.DEFAULT_LANGUAGE)
    i18n: Optional[JsonI18n] = i18n_data.get("i18n_instance")
    _ = lambda key, **kwargs: i18n.gettext(current_lang, key, **kwargs) if i18n else key

    if not i18n or not callback.message:
        await callback.answer(_("error_occurred_try_again"), show_alert=True)
        return

    try:
        action_prefix, months_raw, price_raw, sale_mode = callback.data.split(":", 3)
        months = float(months_raw)
    except ValueError:
        await callback.answer(_("error_try_again"), show_alert=True)
        return

    resolved_price = await resolve_fiat_offer_price_for_user(
        session,
        settings,
        callback.from_user.id,
        months,
        sale_mode,
        promo_code_service=promo_code_service,
    )
    if resolved_price is None:
        await callback.answer(_("error_try_again"), show_alert=True)
        return

    user = await user_dal.get_user_by_id(session, callback.from_user.id)
    balance_rub = float(getattr(user, "balance_rub", 0.0) or 0.0)
    if balance_rub + 1e-9 < float(resolved_price):
        await callback.answer(
            _("referral_withdraw_insufficient_balance"),
            show_alert=True,
        )
        return

    payment = await payment_dal.create_payment_record(
        session,
        {
            "user_id": callback.from_user.id,
            "amount": float(resolved_price),
            "currency": "RUB",
            "status": "succeeded",
            "description": "Balance purchase",
            "subscription_duration_months": int(months) if sale_mode != "traffic" else 0,
            "provider": "balance",
        },
    )
    balance_tx = await referral_finance_dal.spend_balance(
        session,
        callback.from_user.id,
        float(resolved_price),
        description="Subscription purchase from balance",
        payment_id=payment.payment_id,
    )
    if not balance_tx:
        await callback.answer(_("referral_withdraw_insufficient_balance"), show_alert=True)
        return

    activation = await subscription_service.activate_subscription(
        session=session,
        user_id=callback.from_user.id,
        months=int(months) if sale_mode != "traffic" else 0,
        payment_amount=float(resolved_price),
        payment_db_id=payment.payment_id,
        provider="balance",
        sale_mode=sale_mode,
        traffic_gb=months if sale_mode == "traffic" else None,
    )
    if not activation or not activation.get("end_date"):
        await session.rollback()
        await callback.answer(_("error_try_again"), show_alert=True)
        return

    await session.commit()

    raw_config_link = activation.get("subscription_url")
    config_link_display, connect_button_url = await prepare_config_links(settings, raw_config_link)
    config_link_text = config_link_display or _("config_link_not_available")
    details_message = (
        _("payment_successful_traffic_full",
          traffic_gb=str(int(months)) if float(months).is_integer() else f"{months:g}",
          end_date=activation["end_date"].strftime("%Y-%m-%d"),
          config_link=config_link_text)
        if sale_mode == "traffic"
        else _("payment_successful_full",
               months=int(months),
               end_date=activation["end_date"].strftime("%Y-%m-%d"),
               config_link=config_link_text)
    )
    details_markup = get_connect_and_main_keyboard(
        current_lang,
        i18n,
        settings,
        config_link_display,
        connect_button_url=connect_button_url,
        preserve_message=True,
    )
    await callback.message.answer(
        details_message,
        reply_markup=details_markup,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    await callback.answer()
