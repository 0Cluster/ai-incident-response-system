# PostgreSQL Performance

## Symptoms

- Slow queries
- High connection count
- Lock contention

## Investigation

- pg_stat_activity
- EXPLAIN ANALYZE
- VACUUM status

## Recommended Actions

- Terminate idle connections.
- Optimize slow queries.
- Add indexes.
- Vacuum and analyze tables.
