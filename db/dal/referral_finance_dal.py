import logging
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import BalanceTransaction, ReferralSetting, User, WithdrawalRequest


async def get_or_create_referral_settings(session: AsyncSession) -> ReferralSetting:
    settings = await session.get(ReferralSetting, 1)
    if settings:
        return settings

    settings = ReferralSetting(id=1, commission_percent=0)
    session.add(settings)
    await session.flush()
    await session.refresh(settings)
    return settings


async def get_referral_commission_percent(session: AsyncSession) -> int:
    settings = await get_or_create_referral_settings(session)
    return max(0, min(100, int(settings.commission_percent or 0)))


async def set_referral_commission_percent(
    session: AsyncSession,
    percent: int,
) -> ReferralSetting:
    settings = await get_or_create_referral_settings(session)
    settings.commission_percent = max(0, min(100, int(percent)))
    settings.updated_at = datetime.now(timezone.utc)
    await session.flush()
    await session.refresh(settings)
    return settings


async def get_balance_transaction_by_payment(
    session: AsyncSession,
    payment_id: int,
    transaction_type: str,
) -> Optional[BalanceTransaction]:
    stmt = select(BalanceTransaction).where(
        BalanceTransaction.payment_id == payment_id,
        BalanceTransaction.transaction_type == transaction_type,
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def add_user_balance(
    session: AsyncSession,
    user_id: int,
    amount_rub: float,
) -> Optional[User]:
    user = await session.get(User, user_id)
    if not user:
        return None
    user.balance_rub = float(user.balance_rub or 0.0) + float(amount_rub)
    await session.flush()
    await session.refresh(user)
    return user


async def credit_balance_from_payment(
    session: AsyncSession,
    user_id: int,
    payment_id: int,
    amount_rub: float,
    description: str = "Balance top-up",
) -> Optional[BalanceTransaction]:
    if amount_rub <= 0:
        return None

    existing = await get_balance_transaction_by_payment(
        session,
        payment_id,
        "balance_topup",
    )
    if existing:
        return existing

    user = await session.get(User, user_id)
    if not user:
        return None

    user.balance_rub = float(user.balance_rub or 0.0) + float(amount_rub)
    tx = BalanceTransaction(
        user_id=user_id,
        amount_rub=float(amount_rub),
        transaction_type="balance_topup",
        status="completed",
        description=description,
        payment_id=payment_id,
    )
    session.add(tx)
    await session.flush()
    await session.refresh(tx)
    return tx


async def credit_balance_from_promo(
    session: AsyncSession,
    user_id: int,
    amount_rub: float,
    promo_code: str,
) -> Optional[BalanceTransaction]:
    if amount_rub <= 0:
        return None

    user = await session.get(User, user_id)
    if not user:
        return None

    user.balance_rub = float(user.balance_rub or 0.0) + float(amount_rub)
    tx = BalanceTransaction(
        user_id=user_id,
        amount_rub=float(amount_rub),
        transaction_type="promo_balance_credit",
        status="completed",
        description=f"Promo code {promo_code}",
    )
    session.add(tx)
    await session.flush()
    await session.refresh(tx)
    return tx


async def add_referral_reward(
    session: AsyncSession,
    inviter_user_id: int,
    referee_user_id: int,
    payment_id: int,
    amount_rub: float,
    percent: int,
) -> Optional[BalanceTransaction]:
    if amount_rub <= 0:
        return None

    existing = await get_balance_transaction_by_payment(
        session,
        payment_id,
        "referral_reward",
    )
    if existing:
        return existing

    user = await session.get(User, inviter_user_id)
    if not user:
        return None

    user.balance_rub = float(user.balance_rub or 0.0) + float(amount_rub)
    user.referral_total_earned_rub = float(user.referral_total_earned_rub or 0.0) + float(amount_rub)

    tx = BalanceTransaction(
        user_id=inviter_user_id,
        amount_rub=float(amount_rub),
        transaction_type="referral_reward",
        status="completed",
        description=f"Referral reward {percent}% from user {referee_user_id}",
        payment_id=payment_id,
        related_user_id=referee_user_id,
    )
    session.add(tx)
    await session.flush()
    await session.refresh(tx)
    return tx


async def spend_balance(
    session: AsyncSession,
    user_id: int,
    amount_rub: float,
    description: str,
    payment_id: Optional[int] = None,
) -> Optional[BalanceTransaction]:
    if amount_rub <= 0:
        return None

    user = await session.get(User, user_id)
    if not user:
        return None

    balance = float(user.balance_rub or 0.0)
    if balance + 1e-9 < float(amount_rub):
        return None

    user.balance_rub = balance - float(amount_rub)
    tx = BalanceTransaction(
        user_id=user_id,
        amount_rub=-float(amount_rub),
        transaction_type="balance_purchase",
        status="completed",
        description=description,
        payment_id=payment_id,
    )
    session.add(tx)
    await session.flush()
    await session.refresh(tx)
    return tx


async def create_withdrawal_request(
    session: AsyncSession,
    user_id: int,
    amount_rub: float,
    payment_details: str,
) -> Optional[WithdrawalRequest]:
    if amount_rub <= 0:
        return None

    user = await session.get(User, user_id)
    if not user:
        return None

    balance = float(user.balance_rub or 0.0)
    withdrawable_balance = await get_withdrawable_referral_balance(session, user_id)
    if balance + 1e-9 < float(amount_rub) or withdrawable_balance + 1e-9 < float(amount_rub):
        return None

    user.balance_rub = balance - float(amount_rub)
    request = WithdrawalRequest(
        user_id=user_id,
        amount_rub=float(amount_rub),
        payment_details=payment_details.strip(),
        status="pending",
    )
    session.add(request)
    await session.flush()

    tx = BalanceTransaction(
        user_id=user_id,
        amount_rub=-float(amount_rub),
        transaction_type="withdraw_request",
        status="pending",
        description="Withdrawal request created",
        withdrawal_request_id=request.request_id,
    )
    session.add(tx)
    await session.flush()
    await session.refresh(request)
    return request


async def get_withdrawable_referral_balance(
    session: AsyncSession,
    user_id: int,
) -> float:
    user = await session.get(User, user_id)
    if not user:
        return 0.0

    withdrawn_stmt = select(
        func.coalesce(func.sum(WithdrawalRequest.amount_rub), 0.0)
    ).where(
        WithdrawalRequest.user_id == user_id,
        WithdrawalRequest.status.in_(("pending", "approved")),
    )
    withdrawn_result = await session.execute(withdrawn_stmt)
    reserved_or_paid = float(withdrawn_result.scalar() or 0.0)

    total_referral_earned = float(user.referral_total_earned_rub or 0.0)
    current_balance = float(user.balance_rub or 0.0)
    withdrawable = max(0.0, total_referral_earned - reserved_or_paid)
    return min(current_balance, withdrawable)


async def get_withdrawal_request(
    session: AsyncSession,
    request_id: int,
) -> Optional[WithdrawalRequest]:
    return await session.get(WithdrawalRequest, request_id)


async def list_pending_withdrawal_requests(
    session: AsyncSession,
) -> List[WithdrawalRequest]:
    stmt = (
        select(WithdrawalRequest)
        .where(WithdrawalRequest.status == "pending")
        .order_by(WithdrawalRequest.created_at.asc())
    )
    result = await session.execute(stmt)
    return result.scalars().all()


async def get_pending_withdrawal_count(session: AsyncSession) -> int:
    requests = await list_pending_withdrawal_requests(session)
    return len(requests)


async def approve_withdrawal_request(
    session: AsyncSession,
    request_id: int,
    admin_user_id: int,
) -> Optional[WithdrawalRequest]:
    request = await session.get(WithdrawalRequest, request_id)
    if not request or request.status != "pending":
        return None

    request.status = "approved"
    request.admin_user_id = admin_user_id
    request.processed_at = datetime.now(timezone.utc)

    stmt = select(BalanceTransaction).where(
        BalanceTransaction.withdrawal_request_id == request_id,
        BalanceTransaction.transaction_type == "withdraw_request",
    )
    tx_result = await session.execute(stmt)
    tx = tx_result.scalar_one_or_none()
    if tx:
        tx.status = "completed"

    await session.flush()
    await session.refresh(request)
    return request


async def reject_withdrawal_request(
    session: AsyncSession,
    request_id: int,
    admin_user_id: int,
) -> Optional[WithdrawalRequest]:
    request = await session.get(WithdrawalRequest, request_id)
    if not request or request.status != "pending":
        return None

    user = await session.get(User, request.user_id)
    if not user:
        logging.warning("Cannot refund rejected withdrawal request %s: user missing", request_id)
        return None

    request.status = "rejected"
    request.admin_user_id = admin_user_id
    request.processed_at = datetime.now(timezone.utc)

    user.balance_rub = float(user.balance_rub or 0.0) + float(request.amount_rub)

    stmt = select(BalanceTransaction).where(
        BalanceTransaction.withdrawal_request_id == request_id,
        BalanceTransaction.transaction_type == "withdraw_request",
    )
    tx_result = await session.execute(stmt)
    tx = tx_result.scalar_one_or_none()
    if tx:
        tx.status = "cancelled"

    refund_tx = BalanceTransaction(
        user_id=request.user_id,
        amount_rub=float(request.amount_rub),
        transaction_type="withdraw_reject_refund",
        status="completed",
        description="Withdrawal request rejected, funds returned",
        withdrawal_request_id=request_id,
    )
    session.add(refund_tx)
    await session.flush()
    await session.refresh(request)
    return request


async def get_recent_balance_transactions(
    session: AsyncSession,
    user_id: int,
    limit: int = 10,
) -> List[BalanceTransaction]:
    stmt = (
        select(BalanceTransaction)
        .where(BalanceTransaction.user_id == user_id)
        .order_by(BalanceTransaction.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return result.scalars().all()
