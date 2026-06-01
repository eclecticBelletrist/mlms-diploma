# /new-migration

Generate a new Alembic migration file for a schema change.

## Usage

Call this command with a description of what the migration does.
Example: `/new-migration add embedding index to skills table`

## Steps

1. Ask (if not provided): what schema change does this migration implement?

2. Check existing migrations to avoid conflicts:
   ```bash
   ls alembic/versions/ | sort
   ```

3. Generate the migration file:
   ```bash
   alembic revision --autogenerate -m "<description>"
   ```

4. Open the generated file and verify:
   - `upgrade()` function does exactly what was requested — nothing extra
   - `downgrade()` function correctly reverses the change
   - For hypertable operations: `create_hypertable` in upgrade, `execute("DROP TABLE...")` in downgrade
   - No unintended table modifications from autogenerate noise

5. Run the migration on the dev database:
   ```bash
   alembic upgrade head
   ```

6. Verify the schema applied:
   ```bash
   alembic current
   ```

## Rules

- Never add columns not requested
- If autogenerate includes unexpected changes, remove them and explain why they appeared
- HNSW index creation: use `CREATE INDEX ... USING hnsw (embedding vector_cosine_ops)` — not btree
- TimescaleDB hypertables: `SELECT create_hypertable(...)` must run AFTER the CREATE TABLE in the same migration

## Success criteria

- Migration file created with correct sequential number
- `alembic upgrade head` completes without error
- `alembic current` shows the new revision as head
