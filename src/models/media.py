from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Media:
    """Base class for a deletable media unit."""

    title: str
    added_date: datetime | None
    file_size: int  # bytes

    # Play data (from Jellyfin and/or Plex, for deletion priority)
    jellyfin_id: str | None = None
    plex_id: str | None = None
    last_played_date: datetime | None = None
    play_count: int = 0

    def __repr__(self) -> str:
        added = self.added_date.date() if self.added_date else "unknown"
        size_gb = self.file_size / (1024**3)
        return f"{self.__class__.__name__}('{self.title}', added={added}, {size_gb:.1f}GB)"


@dataclass
class Movie(Media):
    """A movie — atomic deletable unit."""

    radarr_id: int | None = None
    imdb_id: str | None = None
    tmdb_id: int | None = None


@dataclass
class Season(Media):
    """A single season of a TV show — atomic deletable unit."""

    sonarr_series_id: int | None = None
    series_title: str = ""
    season_number: int = 0
    episode_file_ids: list[int] = field(default_factory=list)
    episode_ids: list[int] = field(default_factory=list)
    imdb_id: str | None = None
    tvdb_id: int | None = None
