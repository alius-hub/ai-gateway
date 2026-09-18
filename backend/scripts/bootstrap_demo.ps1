$ErrorActionPreference = "Stop"

Write-Host "Using database URL from current ENV..."
uv run python -c "from app.core.config import get_settings; print(get_settings().database_url)"

Write-Host "Applying migrations..."
uv run alembic upgrade head

Write-Host "Seeding demo data..."
uv run python scripts/seed_demo_data.py

Write-Host "Done."
