"""rfqs invitations events

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-24
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0003'
down_revision: str | None = '0002'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Human-readable RFQ references: RFQ-<year>-<6-digit sequence>.
    op.execute("CREATE SEQUENCE IF NOT EXISTS rfq_reference_seq")

    op.create_table('rfqs',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('reference_id', sa.String(length=32), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('buyer_id', sa.UUID(), nullable=False),
    sa.Column('is_british_auction', sa.Boolean(), nullable=False),
    sa.Column('bid_start_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('bid_close_at', sa.DateTime(timezone=True), nullable=False, comment='Originally scheduled close'),
    sa.Column('current_close_at', sa.DateTime(timezone=True), nullable=False, comment='Moves forward on each extension'),
    sa.Column('forced_close_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('pickup_date', sa.Date(), nullable=False),
    sa.Column('status', sa.Enum('SCHEDULED', 'ACTIVE', 'CLOSED', 'FORCE_CLOSED', 'CANCELLED', name='rfq_status'), server_default='SCHEDULED', nullable=False),
    sa.Column('currency', sa.String(length=3), server_default='INR', nullable=False),
    sa.Column('extension_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name=op.f('ck_rfqs_currency_iso')),
    sa.CheckConstraint('bid_close_at > bid_start_at', name=op.f('ck_rfqs_close_after_start')),
    sa.CheckConstraint('current_close_at <= forced_close_at', name=op.f('ck_rfqs_current_within_forced')),
    sa.CheckConstraint('current_close_at >= bid_close_at', name=op.f('ck_rfqs_current_not_before_close')),
    sa.CheckConstraint('extension_count >= 0', name=op.f('ck_rfqs_extension_count_non_negative')),
    sa.CheckConstraint('forced_close_at > bid_close_at', name=op.f('ck_rfqs_forced_after_close')),
    sa.ForeignKeyConstraint(['buyer_id'], ['users.id'], name=op.f('fk_rfqs_buyer_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_rfqs')),
    sa.UniqueConstraint('reference_id', name=op.f('uq_rfqs_reference_id'))
    )
    op.create_index('ix_rfqs_buyer_created', 'rfqs', ['buyer_id', 'created_at'], unique=False)
    op.create_index('ix_rfqs_status_close', 'rfqs', ['status', 'current_close_at'], unique=False)
    op.create_index('ix_rfqs_status_start', 'rfqs', ['status', 'bid_start_at'], unique=False)
    op.create_table('supplier_invites',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('email', postgresql.CITEXT(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('invited_by', sa.UUID(), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('accepted_user_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['accepted_user_id'], ['users.id'], name=op.f('fk_supplier_invites_accepted_user_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['invited_by'], ['users.id'], name=op.f('fk_supplier_invites_invited_by_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_supplier_invites')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_supplier_invites_token_hash'))
    )
    op.create_index('uq_supplier_invites_pending_email', 'supplier_invites', ['email'], unique=True, postgresql_where=sa.text('accepted_at IS NULL'))
    op.create_table('auction_configs',
    sa.Column('rfq_id', sa.UUID(), nullable=False),
    sa.Column('trigger_window_minutes', sa.Integer(), nullable=False),
    sa.Column('extension_minutes', sa.Integer(), nullable=False),
    sa.Column('trigger_type', sa.Enum('BID_RECEIVED', 'ANY_RANK_CHANGE', 'L1_RANK_CHANGE', name='auction_trigger_type'), nullable=False),
    sa.CheckConstraint('extension_minutes BETWEEN 1 AND 1440', name=op.f('ck_auction_configs_extension_range')),
    sa.CheckConstraint('trigger_window_minutes BETWEEN 1 AND 1440', name=op.f('ck_auction_configs_trigger_window_range')),
    sa.ForeignKeyConstraint(['rfq_id'], ['rfqs.id'], name=op.f('fk_auction_configs_rfq_id_rfqs'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('rfq_id', name=op.f('pk_auction_configs'))
    )
    op.create_table('auction_events',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('rfq_id', sa.UUID(), nullable=False),
    sa.Column('event_type', sa.String(length=40), nullable=False),
    sa.Column('actor_id', sa.UUID(), nullable=True),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], name=op.f('fk_auction_events_actor_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['rfq_id'], ['rfqs.id'], name=op.f('fk_auction_events_rfq_id_rfqs'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_auction_events'))
    )
    op.create_index('ix_auction_events_rfq_id_id', 'auction_events', ['rfq_id', 'id'], unique=False)
    op.create_table('rfq_invitations',
    sa.Column('rfq_id', sa.UUID(), nullable=False),
    sa.Column('invitee_email', postgresql.CITEXT(), nullable=False),
    sa.Column('supplier_id', sa.UUID(), nullable=True),
    sa.Column('invited_by', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_notified_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['invited_by'], ['users.id'], name=op.f('fk_rfq_invitations_invited_by_users'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['rfq_id'], ['rfqs.id'], name=op.f('fk_rfq_invitations_rfq_id_rfqs'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['supplier_id'], ['users.id'], name=op.f('fk_rfq_invitations_supplier_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('rfq_id', 'invitee_email', name=op.f('pk_rfq_invitations'))
    )
    op.create_index('ix_rfq_invitations_invitee_email', 'rfq_invitations', ['invitee_email'], unique=False)
    op.create_index('ix_rfq_invitations_supplier_id', 'rfq_invitations', ['supplier_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_rfq_invitations_supplier_id', table_name='rfq_invitations')
    op.drop_index('ix_rfq_invitations_invitee_email', table_name='rfq_invitations')
    op.drop_table('rfq_invitations')
    op.drop_index('ix_auction_events_rfq_id_id', table_name='auction_events')
    op.drop_table('auction_events')
    op.drop_table('auction_configs')
    op.drop_index('uq_supplier_invites_pending_email', table_name='supplier_invites', postgresql_where=sa.text('accepted_at IS NULL'))
    op.drop_table('supplier_invites')
    op.drop_index('ix_rfqs_status_start', table_name='rfqs')
    op.drop_index('ix_rfqs_status_close', table_name='rfqs')
    op.drop_index('ix_rfqs_buyer_created', table_name='rfqs')
    op.drop_table('rfqs')
    op.execute("DROP SEQUENCE IF EXISTS rfq_reference_seq")
    sa.Enum(name='auction_trigger_type').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='rfq_status').drop(op.get_bind(), checkfirst=True)
