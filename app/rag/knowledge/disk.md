# Disk Space Alert

## Symptoms

- Filesystem above 90%
- Unable to write logs
- Database failures

## Investigation

- df -h
- du -sh /*
- journalctl

## Recommended Actions

- Delete temporary files.
- Rotate logs.
- Remove unused Docker images.
- Expand disk if required.
