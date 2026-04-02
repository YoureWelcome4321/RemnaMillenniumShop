import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from typing import Optional, Dict, Any
from aiogram import Bot
from datetime import datetime, timezone

from config.settings import Settings
from db.dal import user_dal
from db.dal import payment_dal, referral_finance_dal
from bot.middlewares.i18n import JsonI18n
from .subscription_service import SubscriptionService


class ReferralService:

    def __init__(self, settings: Settings,
                 subscription_service: SubscriptionService, bot: Bot,
                 i18n: JsonI18n):
        self.settings = settings
        self.subscription_service = subscription_service
        self.bot = bot
        self.i18n = i18n

    async def apply_referral_bonuses_for_payment(
            self,
            session: AsyncSession,
            referee_user_id: int,
            purchased_subscription_months: int,
            current_payment_db_id: Optional[int] = None,
            skip_if_active_before_payment: bool = True) -> Dict[str, Any]:
        return {
            "referee_bonus_applied_days": None,
            "referee_new_end_date": None,
            "inviter_bonus_applied_flag": False,
        }

    async def reward_referrer_for_payment(
        self,
        session: AsyncSession,
        referee_user_id: int,
        payment_amount_rub: float,
        current_payment_db_id: Optional[int],
    ) -> Dict[str, Any]:
        if (
            not getattr(self.settings, "REFERRAL_ENABLED", True)
            or not current_payment_db_id
            or payment_amount_rub <= 0
        ):
            return {"reward_amount_rub": 0.0, "commission_percent": 0, "inviter_user_id": None}

        referee_user = await user_dal.get_user_by_id(session, referee_user_id)
        if not referee_user or not referee_user.referred_by_id:
            return {"reward_amount_rub": 0.0, "commission_percent": 0, "inviter_user_id": None}

        commission_percent = await referral_finance_dal.get_referral_commission_percent(session)
        if commission_percent <= 0:
            return {"reward_amount_rub": 0.0, "commission_percent": 0, "inviter_user_id": referee_user.referred_by_id}

        reward_amount = round(float(payment_amount_rub) * commission_percent / 100.0, 2)
        if reward_amount <= 0:
            return {"reward_amount_rub": 0.0, "commission_percent": commission_percent, "inviter_user_id": referee_user.referred_by_id}

        tx = await referral_finance_dal.add_referral_reward(
            session=session,
            inviter_user_id=referee_user.referred_by_id,
            referee_user_id=referee_user_id,
            payment_id=current_payment_db_id,
            amount_rub=reward_amount,
            percent=commission_percent,
        )
        if not tx:
            return {"reward_amount_rub": 0.0, "commission_percent": commission_percent, "inviter_user_id": referee_user.referred_by_id}

        inviter = await user_dal.get_user_by_id(session, referee_user.referred_by_id)
        referee_name = referee_user.first_name or f"User {referee_user_id}"
        if inviter:
            inviter_lang = inviter.language_code or self.settings.DEFAULT_LANGUAGE
            _ = lambda key, **kwargs: self.i18n.gettext(inviter_lang, key, **kwargs)
            try:
                await self.bot.send_message(
                    inviter.user_id,
                    _(
                        "referral_reward_inviter_notification",
                        referee_name=referee_name,
                        amount=reward_amount,
                        percent=commission_percent,
                        balance=float(inviter.balance_rub or 0.0),
                    ),
                    parse_mode="HTML",
                )
            except Exception as exc:
                logging.error("Failed to notify inviter %s about referral reward: %s", inviter.user_id, exc)

        return {
            "reward_amount_rub": reward_amount,
            "commission_percent": commission_percent,
            "inviter_user_id": referee_user.referred_by_id,
        }

    async def generate_referral_link(self, session: AsyncSession,
                                     bot_username: str,
                                     inviter_user_id: int) -> Optional[str]:
        if not getattr(self.settings, "REFERRAL_ENABLED", True):
            return None

        try:
            user = await user_dal.get_user_by_id(session, inviter_user_id)
            if not user:
                logging.warning(
                    "Unable to generate referral link: user %s not found.",
                    inviter_user_id,
                )
                return None

            referral_code = await user_dal.ensure_referral_code(session, user)
            if not referral_code:
                logging.warning(
                    "User %s has no referral code even after regeneration attempt.",
                    inviter_user_id,
                )
                return None

            return f"https://t.me/{bot_username}?start=ref_u{referral_code}"
        except Exception as exc:
            logging.error(
                "Failed to generate referral link for user %s: %s",
                inviter_user_id,
                exc,
                exc_info=True,
            )
            return None

    async def get_referral_stats(self, session: AsyncSession, user_id: int) -> dict:
        """Get referral statistics for a user"""
        try:
            user = await user_dal.get_user_by_id(session, user_id)
            commission_percent = await referral_finance_dal.get_referral_commission_percent(session)

            # Count total invited users (referrals)
            invited_count_result = await session.execute(
                text("SELECT COUNT(*) FROM users WHERE referred_by_id = :user_id"),
                {"user_id": user_id}
            )
            invited_count = invited_count_result.scalar() or 0
            
            # Count users who made successful payments (purchased subscription)
            purchased_count_result = await session.execute(
                text("""
                    SELECT COUNT(DISTINCT u.user_id) 
                    FROM users u 
                    JOIN payments p ON u.user_id = p.user_id 
                    WHERE u.referred_by_id = :user_id 
                    AND p.status = 'succeeded'
                """),
                {"user_id": user_id}
            )
            purchased_count = purchased_count_result.scalar() or 0
            
            return {
                "invited_count": invited_count,
                "purchased_count": purchased_count,
                "balance_rub": float(getattr(user, "balance_rub", 0.0) or 0.0),
                "referral_total_earned_rub": float(getattr(user, "referral_total_earned_rub", 0.0) or 0.0),
                "commission_percent": commission_percent,
            }
        except Exception as e:
            logging.error(f"Error getting referral stats for user {user_id}: {e}")
            return {
                "invited_count": 0,
                "purchased_count": 0,
                "balance_rub": 0.0,
                "referral_total_earned_rub": 0.0,
                "commission_percent": 0,
            }
