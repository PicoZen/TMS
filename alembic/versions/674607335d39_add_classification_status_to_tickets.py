"""Add classification status to tickets

Revision ID: 674607335d39
Revises: 7e9bc75c81bc
Create Date: 2026-07-16 17:07:08.354921

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '674607335d39'
down_revision: Union[str, None] = '7e9bc75c81bc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Portable enum creation - sa.Enum(...).create() compiles to a native
    # CREATE TYPE on Postgres and is a harmless no-op on SQLite (which has
    # no user-defined types and represents this as VARCHAR + CHECK instead).
    # A raw `op.execute("CREATE TYPE ...")` here would hard-fail on SQLite -
    # this migration previously did that; it's masked in this repo's test
    # suite because tests build the schema via Base.metadata.create_all()
    # rather than running Alembic, but it would break the first time anyone
    # runs `alembic upgrade head` against a SQLite DATABASE_URL.
    classification_status_enum = sa.Enum(
        'PENDING', 'PROCESSING', 'COMPLETED', 'FAILED', name='classificationstatus'
    )
    classification_status_enum.create(op.get_bind(), checkfirst=True)
    op.add_column(
        'tickets',
        sa.Column(
            'classification_status',
            sa.Enum(
                'PENDING', 'PROCESSING', 'COMPLETED', 'FAILED',
                name='classificationstatus', create_type=False,
            ),
            nullable=False,
            server_default='PENDING',
        ),
    )
    op.add_column('tickets', sa.Column('classification_retry_count', sa.Integer(), nullable=False, server_default='0'))
    op.create_index(op.f('ix_tickets_classification_status'), 'tickets', ['classification_status'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_tickets_classification_status'), table_name='tickets')
    op.drop_column('tickets', 'classification_retry_count')
    op.drop_column('tickets', 'classification_status')
    sa.Enum(name='classificationstatus').drop(op.get_bind(), checkfirst=True)
