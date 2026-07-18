"""Add tsvector full-text search column + GIN index to tickets

Postgres gets a real generated tsvector column, auto-maintained by Postgres
itself on every insert/update - the app never writes to it.
TicketRepository.search() queries this column directly via
websearch_to_tsquery/ts_rank.

Revision ID: a3f7c9e21d40
Revises: 152b79dbcc2a
Create Date: 2026-07-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a3f7c9e21d40'
down_revision: Union[str, None] = '152b79dbcc2a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE tickets
        ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS (
            to_tsvector('english', coalesce(title, '') || ' ' || coalesce(description, ''))
        ) STORED
        """
    )
    op.execute(
        "CREATE INDEX ix_tickets_search_vector ON tickets USING GIN (search_vector)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_tickets_search_vector")
    op.execute("ALTER TABLE tickets DROP COLUMN IF EXISTS search_vector")
