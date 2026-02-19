# Purgarr

Automated disk cleanup for media server stacks. Deletes the oldest movies and TV seasons when your disk runs low — with full cleanup across Radarr, Sonarr, Jellyfin, Plex, and qBittorrent.

```
                     Purgarr
                        |
          +-------------+-------------+
          |             |             |
       Radarr        Sonarr      Jellyfin/Plex
     (movies)      (seasons)     (library cleanup)
          |             |
     qBittorrent   qBittorrent
   (torrent cleanup)
```

## Features

- **Season-level granularity** — deletes individual seasons (e.g. Dexter S1), not entire series
- **Two independent modes** — space-based (reactive) and age-based (proactive), combinable
- **Safe download cleanup** — removes torrents via qBittorrent API, never blindly scans the filesystem
- **Full stack cleanup** — Radarr/Sonarr deletion, Jellyfin entry removal, Plex trash emptying, qBittorrent torrent removal
- **Race condition prevention** — unmonitors episodes in Sonarr before deleting files, preventing automatic re-search
- **Recently-played protection** — content played in the last 30 days is deprioritized (deleted last)
- **Dry-run by default** — preview what would be deleted before enabling real deletions
- **Cron scheduling** — runs on a configurable schedule inside the container

## Modes

| Mode | Trigger | Behavior | Use case |
|------|---------|----------|----------|
| **Space** | Free disk < threshold | Deletes oldest content until free > threshold, no age restriction | Limited storage — never let the disk fill up |
| **Age** | Content older than X days | Deletes all content older than threshold, regardless of disk space | Rotating library — auto-prune old content |

Enable both, one, or neither:

```env
# Space mode (reactive) — delete when disk is low
SPACE_MODE=true
FREE_SPACE_THRESHOLD_GB=10

# Age mode (proactive) — delete old content regardless of disk space
AGE_MODE=false
MAX_AGE_DAYS=180
```

## Quick Start

### 1. Add to your Docker Compose

```yaml
services:
  purgarr:
    image: ghcr.io/mderouet/purgarr:latest
    container_name: purgarr
    restart: unless-stopped
    mem_limit: 256m
    env_file:
      - .env
    volumes:
      - /mnt/media:/media    # same mount as your *arr stack
```

### 2. Configure `.env`

```env
# Required
RADARR_URL=http://radarr:7878
RADARR_API_KEY=your-radarr-api-key
SONARR_URL=http://sonarr:8989
SONARR_API_KEY=your-sonarr-api-key
JELLYFIN_URL=http://jellyfin:8096
JELLYFIN_API_KEY=your-jellyfin-api-key
MEDIA_PATH=/media

# Optional: Plex (uses host network — use VPS IP, not Docker DNS)
PLEX_URL=http://your-vps-ip:32400
PLEX_TOKEN=your-plex-token

# Optional: qBittorrent (for download folder cleanup)
QBITTORRENT_URL=http://qbittorrent:8080
QBITTORRENT_USERNAME=admin
QBITTORRENT_PASSWORD=your-password

# Modes
SPACE_MODE=true
FREE_SPACE_THRESHOLD_GB=10
AGE_MODE=false
MAX_AGE_DAYS=180

# Safety — start with dry run!
DRY_RUN=true
CRON_SCHEDULE=0 */6 * * *
VERBOSE=false
```

### 3. Start with dry run

```bash
docker compose up -d purgarr
docker logs -f purgarr
```

Check the logs to verify correct oldest-first ordering. When satisfied, set `DRY_RUN=false` and restart.

## Production Example

Purgarr alongside a full *arr stack, cleaning up disk space every 6 hours:

```yaml
services:
  # radarr:  ...    (movie management, port 7878)
  # sonarr:  ...    (TV management, port 8989)
  # jellyfin: ...   (media server, port 8096)
  # plex:    ...    (media server, host network, port 32400)
  # qbittorrent: .. (torrent client, port 8080)
  # seerr:   ...    (request UI, port 5055)

  purgarr:
    image: ghcr.io/mderouet/purgarr:latest
    container_name: purgarr
    restart: unless-stopped
    mem_limit: 256m
    env_file:
      - .env
    volumes:
      - /mnt/media:/media   # must be the same filesystem as the *arr stack
```

```env
# Service connections (use Docker DNS names)
RADARR_URL=http://radarr:7878
RADARR_API_KEY=your-radarr-api-key
SONARR_URL=http://sonarr:8989
SONARR_API_KEY=your-sonarr-api-key
JELLYFIN_URL=http://jellyfin:8096
JELLYFIN_API_KEY=your-jellyfin-api-key
QBITTORRENT_URL=http://qbittorrent:8080
QBITTORRENT_USERNAME=admin
QBITTORRENT_PASSWORD=your-password

# Plex uses host network — use your server IP, not Docker DNS
PLEX_URL=http://your-server-ip:32400
PLEX_TOKEN=your-plex-token

# Seerr — triggers availability sync so removed media disappears from the request UI
SEERR_URL=http://seerr:5055
SEERR_API_KEY=your-seerr-api-key

# Cleanup config
MEDIA_PATH=/media
SPACE_MODE=true
FREE_SPACE_THRESHOLD_GB=10
AGE_MODE=false
MAX_AGE_DAYS=180
DRY_RUN=false
CRON_SCHEDULE=0 */6 * * *
VERBOSE=false
```

## How It Works

On each run, Purgarr:

1. **Collects** all movies from Radarr and all seasons from Sonarr (with file sizes and added dates)
2. **Enriches** with Jellyfin play data — recently-played content is deprioritized
3. **Sorts** everything by `added_date` (oldest first)
4. **Deletes** candidates based on active mode(s):
   - **Age mode**: all items older than `MAX_AGE_DAYS`
   - **Space mode**: oldest items until free space > `FREE_SPACE_THRESHOLD_GB`
5. **Cleans up** across all services after deletion

### Deletion order for a movie

1. Look up torrent hash from Radarr download history
2. Delete movie from Radarr (removes library files)
3. Delete torrent + download files from qBittorrent
4. Delete entry from Jellyfin

### Deletion order for a season

1. Look up torrent hashes from Sonarr download history
2. **Unmonitor** all episodes in the season (prevents Sonarr re-search)
3. Delete episode files from Sonarr
4. If all seasons of the series are now empty, delete the entire series
5. Delete torrent + download files from qBittorrent
6. Delete season entry from Jellyfin

### Post-cleanup

- Trigger Plex library scan + empty trash (removes ghost entries)
- Trigger Jellyfin library refresh
- Log a summary table of everything that was deleted

## Configuration Reference

### Required

| Variable | Description |
|----------|-------------|
| `RADARR_URL` | Radarr API URL (e.g. `http://radarr:7878`) |
| `RADARR_API_KEY` | Radarr API key (Settings > General) |
| `SONARR_URL` | Sonarr API URL (e.g. `http://sonarr:8989`) |
| `SONARR_API_KEY` | Sonarr API key (Settings > General) |
| `JELLYFIN_URL` | Jellyfin API URL (e.g. `http://jellyfin:8096`) |
| `JELLYFIN_API_KEY` | Jellyfin API key (Dashboard > API Keys) |
| `MEDIA_PATH` | Media mount path inside the container (e.g. `/media`) |

### Optional

| Variable | Default | Description |
|----------|---------|-------------|
| `PLEX_URL` | *(disabled)* | Plex API URL. Uses host network — set to VPS IP, not Docker DNS |
| `PLEX_TOKEN` | *(disabled)* | Plex token (from `Preferences.xml` > `PlexOnlineToken`) |
| `QBITTORRENT_URL` | *(disabled)* | qBittorrent Web API URL |
| `QBITTORRENT_USERNAME` | *(empty)* | qBittorrent username |
| `QBITTORRENT_PASSWORD` | *(empty)* | qBittorrent password |
| `SEERR_URL` | *(disabled)* | Seerr API URL (e.g. `http://seerr:5055`) |
| `SEERR_API_KEY` | *(disabled)* | Seerr API key (Settings > General) |

### Modes

| Variable | Default | Description |
|----------|---------|-------------|
| `SPACE_MODE` | `true` | Enable space-based cleanup |
| `FREE_SPACE_THRESHOLD_GB` | `10` | Free space threshold in GB |
| `AGE_MODE` | `false` | Enable age-based cleanup |
| `MAX_AGE_DAYS` | `180` | Delete content older than this many days |

### General

| Variable | Default | Description |
|----------|---------|-------------|
| `DRY_RUN` | `true` | Preview deletions without acting |
| `CRON_SCHEDULE` | *(empty)* | Cron expression for scheduling (e.g. `0 */6 * * *`). If empty, runs once and exits |
| `VERBOSE` | `false` | Enable debug logging |

## Supported Services

| Service | Role | Required |
|---------|------|----------|
| **Radarr** | Movie management + deletion | Yes |
| **Sonarr** | TV series management + season-level deletion | Yes |
| **Jellyfin** | Play data enrichment + entry cleanup | Yes |
| **Plex** | Library scan + trash cleanup | No |
| **qBittorrent** | Torrent + download file cleanup | No |
| **Seerr** | Availability sync after deletions | No |

Plex, qBittorrent, and Seerr are optional — if not configured, Purgarr skips their cleanup steps.

## Safety

- **Dry run by default** — `DRY_RUN=true` out of the box. Nothing is deleted until you explicitly set it to `false`
- **Recently-played deprioritization** — content played in Jellyfin within the last 30 days is moved to the end of the deletion queue
- **Queue awareness** — items actively being imported by Radarr/Sonarr are skipped
- **Empty series cleanup** — when all seasons of a series are deleted, the empty shell is removed from Sonarr to prevent ghost entries in Seerr
- **No filesystem scanning** — download cleanup uses the qBittorrent API exclusively, never blindly deleting files from disk

## Credits

Forked from [Reclaimarr](https://github.com/Okhr/reclaimarr) by [@Okhr](https://github.com/Okhr). Purgarr adds season-level deletion, removes the Jellystat/Jellyseerr dependencies, and adds Plex/qBittorrent integration.
