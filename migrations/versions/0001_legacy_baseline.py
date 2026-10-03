"""Baseline for the original SQLite ERP schema."""

from typing import Sequence, Union

from alembic import op

revision: str = "0001_legacy"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass