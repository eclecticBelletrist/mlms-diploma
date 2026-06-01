# /benchmark

Measure latency p99 and precision@5. Required for NFR-1 and FR-1 acceptance criteria.

## Steps

1. Ensure the synthetic dataset exists:
   ```bash
   ls tests/fixtures/synthetic_100.json || python scripts/seed_test_data.py
   ```

2. Run latency benchmark — cached path (NFR-1 primary):
   ```bash
   pytest tests/benchmark/test_latency.py -k "cached" --benchmark-only \
     --benchmark-json=results/latency_cached.json
   ```

3. Run latency benchmark — cold path (NFR-1 secondary, measured separately):
   ```bash
   pytest tests/benchmark/test_latency.py -k "cold" --benchmark-only \
     --benchmark-json=results/latency_cold.json
   ```

4. Run precision@5 benchmark (FR-1):
   ```bash
   pytest tests/benchmark/test_precision.py \
     --dataset tests/fixtures/synthetic_100.json \
     --benchmark-json=results/precision.json
   ```

5. Report results in this exact format:
   ```
   === BENCHMARK RESULTS ===

   Latency — cached path
     p50: Xms  p95: Xms  p99: Xms
     Target: < 200ms p99  →  PASS / FAIL

   Latency — cold path (includes Embedding API network call)
     p50: Xms  p95: Xms  p99: Xms
     Note: cold path SLA not enforced by NFR-1 (network-dependent)

   Precision@5 (100-scenario synthetic dataset)
     Score: X.XX
     Target: >= 0.80  →  PASS / FAIL

   === END ===
   ```

## Rules

- Cached and cold path latency MUST be reported separately — never merge into one number
- If p99 cached > 200ms: identify the slowest operation and propose a fix before stopping
- If precision@5 < 0.80: check embedding quality and cosine threshold — report which scenarios failed
- Do not round results favorably — report raw benchmark output

## Success criteria

- p99 cached path < 200ms
- precision@5 >= 0.80
- Both benchmark result JSON files saved to `results/`
