"""balance credit promo

Revision ID: 0005_balance_credit_promo
Revises: 0004_referral_balance_and_withdrawals
Create Date: 2026-04-02 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0005_balance_credit_promo"
down_revision: Union[str, Sequence[str], None] = "0004_referral_balance_and_withdrawals"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("promo_codes", sa.Column("balance_credit_rub", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("promo_codes", "balance_credit_rub")
