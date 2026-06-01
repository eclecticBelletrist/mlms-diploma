/**
 * mlms-hooks.ts — MLMS project lifecycle hooks for OpenCode
 *
 * Mirrors .claude/settings.json hooks in native OpenCode TypeScript plugin format.
 * Place in: .opencode/plugins/mlms-hooks.ts
 */

export const MLMSHooks = async ({ $, directory }) => {
  return {

    // ─── PostToolUse: auto-lint Python files after write ─────────────────────
    "tool.execute.after": async (input, output) => {
      const path: string = input?.args?.path ?? input?.args?.file_path ?? ""

      // 1. ruff fix on any Python file
      if (path.endsWith(".py")) {
        try {
          await $`ruff check --fix ${path}`.quiet()
        } catch {
          // ruff exits non-zero when there are unfixable issues — that's fine, we just lint
        }
      }

      // 2. mypy on core layers only (storage/ and tools/)
      if (path.endsWith(".py") && (path.includes("/storage/") || path.includes("/tools/"))) {
        try {
          const result = await $`mypy ${path} --ignore-missing-imports`.text()
          const lines = result.split("\n").slice(-5).join("\n")
          if (result.includes("error:")) {
            console.log(`[MLMS hook] mypy issues in ${path}:\n${lines}`)
          }
        } catch {
          // mypy not installed or config issue — skip silently
        }
      }

      // 3. Migration safety reminder
      if (path.match(/alembic\/versions\/.+\.py$/)) {
        console.log(
          "[MLMS hook] Migration written. Checklist before running:\n" +
          "  - create_hypertable() AFTER CREATE TABLE in same upgrade()\n" +
          "  - VECTOR columns: VECTOR(4096) only\n" +
          "  - HNSW index: USING hnsw (embedding vector_cosine_ops)\n" +
          "  - TTL references: 172800 not 86400\n" +
          "  → Run @migration-reviewer before alembic upgrade head"
        )
      }
    },

    // ─── PreToolUse: guard destructive SQL + alembic checklist ───────────────
    "tool.execute.before": async (input, output) => {
      const cmd: string = input?.args?.command ?? ""

      // Block accidental physical deletes on facts
      if (/\bDELETE\b.+\bfacts\b/i.test(cmd)) {
        console.log(
          "[MLMS hook] ⛔ DELETE on facts detected.\n" +
          "MLMS rule: never physically delete facts — use is_current=FALSE.\n" +
          "If intentional, proceed manually."
        )
      }

      // DROP TABLE / TRUNCATE warning
      if (/\b(DROP TABLE|TRUNCATE)\b/i.test(cmd)) {
        console.log(
          "[MLMS hook] ⚠️  Destructive DDL detected: " + cmd.slice(0, 80) +
          "\nVerify this is intentional and alembic downgrade() is ready."
        )
      }

      // Alembic pre-flight checklist
      if (cmd.includes("alembic")) {
        console.log(
          "[MLMS hook] Alembic command detected. Pre-flight checklist:\n" +
          "  1. hypertable created AFTER its TABLE in the same migration\n" +
          "  2. downgrade() reverses upgrade() exactly\n" +
          "  3. No autogenerate noise from unrelated models\n" +
          "  4. EMBEDDING_DIM=4096 in any VECTOR column\n" +
          "  Tip: run @migration-reviewer first"
        )
      }
    },

    // ─── Compaction: inject MLMS-specific context hints ──────────────────────
    "session.compact.before": async (ctx) => {
      // Append MLMS-critical state to the compaction summary prompt
      ctx.additionalContext = [
        "=== MLMS CRITICAL STATE — preserve verbatim ===",
        "REDIS_SESSION_TTL = 172800 (48h). If you see 86400 anywhere — it is WRONG.",
        "EMBEDDING_DIM = 4096. Never change this.",
        "COSINE_CONFLICT_THRESHOLD = 0.96 = calibration starting point, not fixed param.",
        "Implementation steps 1-13 are ordered — never skip ahead.",
        "facts table: physical DELETE forbidden, use is_current=FALSE.",
        "Conflict detection: must run inside a single PostgreSQL transaction.",
        "7 MCP tools, 8 FR, 5 NFR — do not invent new counts.",
        "=== END MLMS CRITICAL STATE ===",
      ].join("\n")
    },

  }
}
