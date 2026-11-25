"""bids and l1

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-24
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '0004'
down_revision: str | None = '0003'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('bids',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('rfq_id', sa.UUID(), nullable=False),
    sa.Column('supplier_id', sa.UUID(), nullable=False),
    sa.Column('carrier_name', sa.String(length=120), nullable=False),
    sa.Column('freight_charges', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('origin_charges', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('destination_charges', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('total_amount', sa.Numeric(precision=14, scale=2), sa.Computed('freight_charges + origin_charges + destination_charges', persisted=True), nullable=False),
    sa.Column('transit_time_days', sa.Integer(), nullable=False),
    sa.Column('quote_validity_until', sa.Date(), nullable=False),
    sa.Column('idempotency_key', sa.String(length=100), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('freight_charges + origin_charges + destination_charges > 0', name=op.f('ck_bids_total_positive')),
    sa.CheckConstraint('freight_charges >= 0 AND origin_charges >= 0 AND destination_charges >= 0', name=op.f('ck_bids_charges_non_negative')),
    sa.CheckConstraint('transit_time_days BETWEEN 1 AND 365', name=op.f('ck_bids_transit_range')),
    sa.ForeignKeyConstraint(['rfq_id'], ['rfqs.id'], name=op.f('fk_bids_rfq_id_rfqs'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['supplier_id'], ['users.id'], name=op.f('fk_bids_supplier_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_bids'))
    )
    op.create_index('ix_bids_rfq_supplier_created', 'bids', ['rfq_id', 'supplier_id', 'created_at'], unique=False)
    op.create_index('ix_bids_rfq_total', 'bids', ['rfq_id', 'total_amount', 'created_at'], unique=False)
    op.create_index('uq_bids_supplier_idempotency_key', 'bids', ['rfq_id', 'supplier_id', 'idempotency_key'], unique=True, postgresql_where=sa.text('idempotency_key IS NOT NULL'))
    op.add_column('rfqs', sa.Column('current_l1_amount', sa.Numeric(precision=14, scale=2), nullable=True))
    op.add_column('rfqs', sa.Column('current_l1_bid_id', sa.UUID(), nullable=True))
    op.create_foreign_key('fk_rfqs_l1_bid', 'rfqs', 'bids', ['current_l1_bid_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    op.drop_constraint('fk_rfqs_l1_bid', 'rfqs', type_='foreignkey')
    op.drop_column('rfqs', 'current_l1_bid_id')
    op.drop_column('rfqs', 'current_l1_amount')
    op.drop_index('uq_bids_supplier_idempotency_key', table_name='bids', postgresql_where=sa.text('idempotency_key IS NOT NULL'))
    op.drop_index('ix_bids_rfq_total', table_name='bids')
    op.drop_index('ix_bids_rfq_supplier_created', table_name='bids')
    op.drop_table('bids')
