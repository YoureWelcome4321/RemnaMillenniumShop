"""add referral min withdrawal setting

Revision ID: 0006_referral_min_withdrawal
Revises: 0005_balance_credit_promo
Create Date: 2026-04-02 00:00:01.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0006_referral_min_withdrawal"
down_revision: Union[str, Sequence[str], None] = "0005_balance_credit_promo"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "referral_settings",
        sa.Column("min_withdrawal_rub", sa.Float(), nullable=True),
    )
    op.execute(
        "UPDATE referral_settings SET min_withdrawal_rub = 0 WHERE min_withdrawal_rub IS NULL"
    )
    op.alter_column("referral_settings", "min_withdrawal_rub", nullable=False)


def downgrade() -> None:
    op.drop_column("referral_settings", "min_withdrawal_rub")
