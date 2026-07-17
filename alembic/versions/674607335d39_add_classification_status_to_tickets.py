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
    # Create the enum type first
    op.execute("CREATE TYPE classificationstatus AS ENUM ('PENDING', 'PROCESSING', 'COMPLETED', 'FAILED')")
    op.add_column('tickets', sa.Column('classification_status', sa.Enum('PENDING', 'PROCESSING', 'COMPLETED', 'FAILED', name='classificationstatus', create_type=False), nullable=False, server_default='PENDING'))
    op.add_column('tickets', sa.Column('classification_retry_count', sa.Integer(), nullable=False, server_default='0'))
    op.create_index(op.f('ix_tickets_classification_status'), 'tickets', ['classification_status'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_tickets_classification_status'), table_name='tickets')
    op.drop_column('tickets', 'classification_retry_count')
    op.drop_column('tickets', 'classification_status')
    op.execute("DROP TYPE classificationstatus")
