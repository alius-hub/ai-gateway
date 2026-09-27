"""Store encrypted API keys for administrator re-viewing.

Revision ID: 20260927_0015
Revises: 20260927_0014
"""

import sqlalchemy as sa
from alembic import op

revision = "20260927_0015"
down_revision = "20260927_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Historical SHA-256 hashes cannot be decrypted; they remain valid until rotated.
    op.add_column("api_keys", sa.Column("key_ciphertext", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("api_keys", "key_ciphertext")
