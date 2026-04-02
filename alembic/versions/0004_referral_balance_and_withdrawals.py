"""referral balance and withdrawals

Revision ID: 0004_referral_balance_and_withdrawals
Revises: 0003_promo_curr_act_not_null
Create Date: 2026-04-02 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0004_referral_balance_and_withdrawals"
down_revision: Union[str, Sequence[str], None] = "0003_promo_curr_act_not_null"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("balance_rub", sa.Float(), nullable=True))
    op.add_column("users", sa.Column("referral_total_earned_rub", sa.Float(), nullable=True))
    op.execute("UPDATE users SET balance_rub = 0 WHERE balance_rub IS NULL")
    op.execute(
        "UPDATE users SET referral_total_earned_rub = 0 WHERE referral_total_earned_rub IS NULL"
    )
    op.alter_column("users", "balance_rub", nullable=False)
    op.alter_column("users", "referral_total_earned_rub", nullable=False)

    op.create_table(
        "referral_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("commission_percent", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        "INSERT INTO referral_settings (id, commission_percent) VALUES (1, 0)"
    )

    op.create_table(
        "withdrawal_requests",
        sa.Column("request_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("amount_rub", sa.Float(), nullable=False),
        sa.Column("payment_details", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("admin_user_id", sa.BigInteger(), nullable=True),
        sa.Column("admin_comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["admin_user_id"], ["users.user_id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"]),
        sa.PrimaryKeyConstraint("request_id"),
    )
    op.create_index("ix_withdrawal_requests_user_id", "withdrawal_requests", ["user_id"], unique=False)
    op.create_index("ix_withdrawal_requests_status", "withdrawal_requests", ["status"], unique=False)
    op.create_index("ix_withdrawal_requests_admin_user_id", "withdrawal_requests", ["admin_user_id"], unique=False)

    op.create_table(
        "balance_transactions",
        sa.Column("transaction_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("amount_rub", sa.Float(), nullable=False),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("transaction_type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("payment_id", sa.Integer(), nullable=True),
        sa.Column("withdrawal_request_id", sa.Integer(), nullable=True),
        sa.Column("related_user_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.payment_id"]),
        sa.ForeignKeyConstraint(["related_user_id"], ["users.user_id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"]),
        sa.ForeignKeyConstraint(["withdrawal_request_id"], ["withdrawal_requests.request_id"]),
        sa.PrimaryKeyConstraint("transaction_id"),
        sa.UniqueConstraint("payment_id", "transaction_type", name="uq_balance_tx_payment_type"),
    )
    op.create_index("ix_balance_transactions_user_id", "balance_transactions", ["user_id"], unique=False)
    op.create_index("ix_balance_transactions_transaction_type", "balance_transactions", ["transaction_type"], unique=False)
    op.create_index("ix_balance_transactions_status", "balance_transactions", ["status"], unique=False)
    op.create_index("ix_balance_transactions_payment_id", "balance_transactions", ["payment_id"], unique=False)
    op.create_index("ix_balance_transactions_withdrawal_request_id", "balance_transactions", ["withdrawal_request_id"], unique=False)
    op.create_index("ix_balance_transactions_related_user_id", "balance_transactions", ["related_user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_balance_transactions_related_user_id", table_name="balance_transactions")
    op.drop_index("ix_balance_transactions_withdrawal_request_id", table_name="balance_transactions")
    op.drop_index("ix_balance_transactions_payment_id", table_name="balance_transactions")
    op.drop_index("ix_balance_transactions_status", table_name="balance_transactions")
    op.drop_index("ix_balance_transactions_transaction_type", table_name="balance_transactions")
    op.drop_index("ix_balance_transactions_user_id", table_name="balance_transactions")
    op.drop_table("balance_transactions")

    op.drop_index("ix_withdrawal_requests_admin_user_id", table_name="withdrawal_requests")
    op.drop_index("ix_withdrawal_requests_status", table_name="withdrawal_requests")
    op.drop_index("ix_withdrawal_requests_user_id", table_name="withdrawal_requests")
    op.drop_table("withdrawal_requests")

    op.drop_table("referral_settings")

    op.drop_column("users", "referral_total_earned_rub")
    op.drop_column("users", "balance_rub")
