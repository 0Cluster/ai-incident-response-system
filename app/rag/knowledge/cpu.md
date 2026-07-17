# High CPU Usage

## Symptoms

- CPU usage above 90%
- High system load
- Slow application response
- Increased request latency

## Possible Causes

- Infinite loops
- Excessive traffic
- CPU-intensive queries
- Background jobs
- Resource contention

## Investigation

- top
- htop
- ps aux --sort=-%cpu
- pidstat
- journalctl

## Recommended Actions

- Identify high CPU processes.
- Restart the affected service if necessary.
- Scale horizontally if sustained.
- Optimize expensive workloads.
