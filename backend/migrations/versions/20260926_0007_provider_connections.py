"""Split provider connection protocols and credentials into reusable records.

Revision ID: 20260926_0007
Revises: 20260926_0006
"""

from alembic import op
import sqlalchemy as sa

revision = "20260926_0007"
down_revision = "20260926_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "provider_protocols",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("provider_id", sa.BigInteger(), sa.ForeignKey("providers.id"), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("protocol_type", sa.String(64), nullable=False),
        sa.Column("base_url", sa.String(255), nullable=False),
        sa.Column("status", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("provider_id", "code", name="uq_provider_protocol_code"),
    )
    op.create_index("ix_provider_protocols_provider_id", "provider_protocols", ["provider_id"])
    op.create_table(
        "provider_secrets",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("provider_id", sa.BigInteger(), sa.ForeignKey("providers.id"), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.Column("status", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("provider_id", "name", name="uq_provider_secret_name"),
    )
    op.create_index("ix_provider_secrets_provider_id", "provider_secrets", ["provider_id"])
    op.add_column("provider_models", sa.Column(
        "protocol_id", sa.BigInteger(), sa.ForeignKey("provider_protocols.id"), nullable=True))
    op.add_column("provider_models", sa.Column(
        "secret_id", sa.BigInteger(), sa.ForeignKey("provider_secrets.id"), nullable=True))
    op.create_index("ix_provider_models_protocol_id", "provider_models", ["protocol_id"])
    op.create_index("ix_provider_models_secret_id", "provider_models", ["secret_id"])

    connection = op.get_bind()
    connection.execute(sa.text("""
        INSERT INTO provider_protocols (provider_id, code, protocol_type, base_url, status)
        SELECT id, 'default', provider_type, base_url, status FROM providers
    """))
    connection.execute(sa.text("""
        INSERT INTO provider_secrets (provider_id, name, ciphertext, status)
        SELECT id, 'default', api_key_ciphertext, 1
        FROM providers WHERE api_key_ciphertext IS NOT NULL
    """))
    connection.execute(sa.text("""
        UPDATE provider_models AS m
        SET protocol_id = p.id
        FROM provider_protocols AS p
        WHERE p.provider_id = m.provider_id AND p.code = 'default'
    """))
    connection.execute(sa.text("""
        UPDATE provider_models AS m
        SET secret_id = s.id
        FROM provider_secrets AS s
        WHERE s.provider_id = m.provider_id AND s.name = 'default'
    """))
    # Legacy columns remain for old installations; child records become the source of truth.
    connection.execute(sa.text("UPDATE providers SET api_key_ciphertext = NULL"))


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(sa.text("""
        UPDATE providers AS p
        SET provider_type = q.protocol_type, base_url = q.base_url
        FROM provider_protocols AS q
        WHERE q.provider_id = p.id AND q.code = 'default'
    """))
    connection.execute(sa.text("""
        UPDATE providers AS p
        SET api_key_ciphertext = s.ciphertext
        FROM provider_secrets AS s
        WHERE s.provider_id = p.id AND s.name = 'default'
    """))
    op.drop_index("ix_provider_models_secret_id", table_name="provider_models")
    op.drop_index("ix_provider_models_protocol_id", table_name="provider_models")
    op.drop_column("provider_models", "secret_id")
    op.drop_column("provider_models", "protocol_id")
    op.drop_index("ix_provider_secrets_provider_id", table_name="provider_secrets")
    op.drop_table("provider_secrets")
    op.drop_index("ix_provider_protocols_provider_id", table_name="provider_protocols")
    op.drop_table("provider_protocols")
