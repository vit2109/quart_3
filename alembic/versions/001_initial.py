"""Initial schema — mirrors create_all models."""

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Schema is created via Base.metadata.create_all at startup.
    # Use autogenerate when ORM models stabilize:
    #   uv run alembic revision --autogenerate -m "initial"
    pass


def downgrade() -> None:
    pass
