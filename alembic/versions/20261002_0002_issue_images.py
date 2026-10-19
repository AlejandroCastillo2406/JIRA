"""add issue images stored in S3

Revision ID: 20261002_0002
Revises: 20261002_0001
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261002_0002"
down_revision = "20261002_0001"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "issue_images",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("issue_id", UUID, sa.ForeignKey("issues.id", ondelete="CASCADE"), nullable=False),
        sa.Column("storage_key", sa.String(700), nullable=False, unique=True),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("caption", sa.String(500)),
        sa.Column("uploaded_by", UUID, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_issue_images_issue_created", "issue_images", ["issue_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_issue_images_issue_created", table_name="issue_images")
    op.drop_table("issue_images")
