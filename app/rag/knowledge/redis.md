# Redis Memory Issues

## Symptoms

- High memory usage
- Evicted keys
- Slow responses

## Investigation

- INFO memory
- INFO stats
- redis-cli monitor

## Recommended Actions

- Increase maxmemory.
- Use eviction policies.
- Remove unnecessary keys.
