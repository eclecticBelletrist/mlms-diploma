# /run-tests

Run the full test suite with coverage and surface actionable failures.

## Steps

1. Run unit tests first (fast feedback):
   ```bash
   pytest tests/unit/ -v --tb=short 2>&1 | head -60
   ```

2. If unit tests pass, run integration tests:
   ```bash
   pytest tests/integration/ -v --tb=short 2>&1 | head -100
   ```

3. Run coverage report:
   ```bash
   pytest tests/ --cov=src/mlms --cov-report=term-missing --cov-fail-under=80
   ```

4. Report back:
   - Overall pass/fail count
   - Coverage percentage
   - Any test below 80% coverage by module
   - Specific failing test names with error summary (not full traceback)

## Success criteria

- All tests pass
- Coverage >= 80% across `src/mlms/`
- No skipped tests without explicit `@pytest.mark.skip` reason

If any test fails, identify the root cause and fix it before reporting done.
Do not report partial success as success.
