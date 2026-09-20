"""Map MusicBrainz genres/tags onto overlapping style playlists.

Clustering is style/sound only — never release year, saved year, or recency.
A track may belong to several playlists (e.g. Southern trap AND Hip-Hop).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

PLAYLIST_PREFIX = "GB "
LEFTOVER_ID = "needs-review"
STYLE_SAMPLE_SIZE = 3
MIN_STYLE_SUGGESTIONS = 8
MAX_STYLE_SUGGESTIONS = 15

# Non-style MusicBrainz tags (nationality, era, meta). Do not cluster on these.
META_LABELS = {
    "seen live",
    "american",
    "british",
    "canadian",
    "australian",
    "german",
    "french",
    "english",
    "irish",
    "scottish",
    "welsh",
    "japanese",
    "swedish",
    "norwegian",
    "danish",
    "dutch",
    "italian",
    "spanish",
    "mexican",
    "brazilian",
    "usa",
    "uk",
    "united states",
    "united kingdom",
    "male vocalists",
    "female vocalists",
    "male vocalist",
    "female vocalist",
    "composer",
    "songwriter",
    "producer",
    "dj",
    "remixer",
    "singer",
    "rapper",
    "band",
    "all",
    "favorite",
    "favourite",
    "beautiful",
    "love",
    "awesome",
    "sexy",
    "check later",
    "2008 universal fire victim",
    "under 2000 listeners",
    "seen-live",
    "70s",
    "80s",
    "90s",
    "00s",
    "60s",
    "50s",
    "2000s",
    "2010s",
    "2020s",
}

# Generic labels that should not create a playlist on their own when stronger
# style evidence already exists (Led Zeppelin is not a pop act).
GENERIC_EXACT = {"pop", "dance", "rock", "electronic", "folk", "blues"}

ERA_RE = re.compile(r"^(?:19|20)\d{2}s?$|^\d{2}s$")


@dataclass(frozen=True)
class StylePlaylist:
    id: str
    name: str
    description: str
    kind: str = "style"


STYLE_PLAYLISTS: tuple[StylePlaylist, ...] = (
    StylePlaylist(
        "hip-hop",
        "GB Hip-Hop & Rap",
        "Liked hip-hop and rap — East Coast, West Coast, drill, and everything in between.",
    ),
    StylePlaylist(
        "southern-trap",
        "GB Southern Trap & Dirty South",
        "Trap, Dirty South, Houston, Memphis, Atlanta, and Southern rap.",
    ),
    StylePlaylist(
        "electronic",
        "GB Electronic & Dance",
        "Broader electronic and dance music spanning club, bass, and melodic producers.",
    ),
    StylePlaylist(
        "house-club",
        "GB House, Techno & Club",
        "House, techno, tech-house, and peak-time club tracks.",
    ),
    StylePlaylist(
        "melodic-electronic",
        "GB Melodic Electronic & Downtempo",
        "Melodic house, downtempo, indietronica, and late-night electronic.",
    ),
    StylePlaylist(
        "bass-edm",
        "GB Bass, Dubstep & Live Electronic",
        "Dubstep, bass music, future bass, and live-electronic festival cuts.",
    ),
    StylePlaylist(
        "rock",
        "GB Rock",
        "The broader rock umbrella: classic, alternative, hard rock, and adjacent guitar music.",
    ),
    StylePlaylist(
        "classic-hard-rock",
        "GB Classic & Hard Rock",
        "Classic rock, hard rock, blues rock, and arena riffs.",
    ),
    StylePlaylist(
        "alt-indie",
        "GB Alternative, Grunge & Indie Rock",
        "Alternative, grunge, indie rock, and guitar-forward left-of-center songs.",
    ),
    StylePlaylist(
        "synth-indie-dance",
        "GB Synthpop, New Wave & Indie Dance",
        "Synth-pop, new wave, dance-punk, and indie-dance grooves.",
    ),
    StylePlaylist(
        "metal-punk",
        "GB Metal, Punk & Heavy",
        "Metal, punk, hardcore, and heavy alternative.",
    ),
    StylePlaylist(
        "jam-funk",
        "GB Jam, Funk & Groove",
        "Jam band, funk, groove rock, and psychedelic pocket.",
    ),
    StylePlaylist(
        "pop-rnb",
        "GB Pop, R&B & Soul",
        "Pop, contemporary R&B, neo-soul, and vocal-led radio songs.",
    ),
    StylePlaylist(
        "reggae-ska",
        "GB Reggae, Ska & Dub",
        "Reggae, ska, ska-punk, dub, and dancehall.",
    ),
    StylePlaylist(
        LEFTOVER_ID,
        "GB Needs Review / Mixed",
        "Leftover liked tracks that still have no confident style cluster after enrichment.",
    ),
)

PLAYLIST_BY_ID = {item.id: item for item in STYLE_PLAYLISTS}

# Specific token sequences → one or more overlapping playlists.
# Longer / more specific keys are matched first.
_STYLE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    # Hip-hop family
    ("southern hip hop", ("southern-trap", "hip-hop")),
    ("dirty south", ("southern-trap", "hip-hop")),
    ("houston rap", ("southern-trap", "hip-hop")),
    ("houston hip hop", ("southern-trap", "hip-hop")),
    ("memphis rap", ("southern-trap", "hip-hop")),
    ("memphis hip hop", ("southern-trap", "hip-hop")),
    ("atlanta rap", ("southern-trap", "hip-hop")),
    ("atlanta hip hop", ("southern-trap", "hip-hop")),
    ("crunk", ("southern-trap", "hip-hop")),
    ("bounce", ("southern-trap", "hip-hop")),
    ("chopped and screwed", ("southern-trap", "hip-hop")),
    ("chopped & screwed", ("southern-trap", "hip-hop")),
    ("phonk", ("southern-trap", "hip-hop")),
    ("country rap", ("southern-trap", "hip-hop")),
    ("gangsta rap", ("hip-hop", "southern-trap")),
    ("trap metal", ("metal-punk", "hip-hop")),
    ("edm trap", ("bass-edm", "electronic")),
    ("festival trap", ("bass-edm", "electronic")),
    ("hybrid trap", ("bass-edm", "electronic")),
    ("trap edm", ("bass-edm", "electronic")),
    ("trap", ("southern-trap", "hip-hop")),
    ("drill", ("hip-hop",)),
    ("grime", ("hip-hop",)),
    ("boom bap", ("hip-hop",)),
    ("g funk", ("hip-hop",)),
    ("conscious hip hop", ("hip-hop",)),
    ("alternative hip hop", ("hip-hop", "alt-indie")),
    ("jazz rap", ("hip-hop",)),
    ("cloud rap", ("hip-hop",)),
    ("pop rap", ("hip-hop", "pop-rnb")),
    ("hip hop", ("hip-hop",)),
    ("hip-hop", ("hip-hop",)),
    ("rap", ("hip-hop",)),
    # House / club
    ("tech house", ("house-club", "electronic")),
    ("progressive house", ("house-club", "melodic-electronic", "electronic")),
    ("deep house", ("house-club", "melodic-electronic", "electronic")),
    ("electro house", ("house-club", "electronic")),
    ("bass house", ("house-club", "bass-edm", "electronic")),
    ("future house", ("house-club", "electronic")),
    ("tropical house", ("house-club", "melodic-electronic", "electronic")),
    ("afro house", ("house-club", "electronic")),
    ("organic house", ("melodic-electronic", "house-club", "electronic")),
    ("melodic house", ("melodic-electronic", "house-club", "electronic")),
    ("melodic techno", ("melodic-electronic", "house-club", "electronic")),
    ("minimal techno", ("house-club", "electronic")),
    ("acid house", ("house-club", "electronic")),
    ("funky house", ("house-club", "electronic")),
    ("soulful house", ("house-club", "electronic")),
    ("uk garage", ("house-club", "electronic")),
    ("speed garage", ("house-club", "electronic")),
    ("future garage", ("melodic-electronic", "electronic")),
    ("big room", ("house-club", "electronic")),
    ("melbourne bounce", ("house-club", "electronic")),
    ("techno", ("house-club", "electronic")),
    ("house", ("house-club", "electronic")),
    ("trance", ("house-club", "electronic")),
    ("edm", ("electronic", "house-club")),
    ("club", ("house-club", "electronic")),
    # Melodic / downtempo electronic
    ("future bass", ("bass-edm", "melodic-electronic", "electronic")),
    ("indietronica", ("melodic-electronic", "synth-indie-dance", "electronic")),
    ("indie electronic", ("melodic-electronic", "synth-indie-dance", "electronic")),
    ("downtempo", ("melodic-electronic", "electronic")),
    ("chillwave", ("melodic-electronic", "electronic")),
    ("chillout", ("melodic-electronic", "electronic")),
    ("chillstep", ("melodic-electronic", "bass-edm", "electronic")),
    ("trip hop", ("melodic-electronic", "electronic")),
    ("trip-hop", ("melodic-electronic", "electronic")),
    ("ambient", ("melodic-electronic", "electronic")),
    ("idm", ("melodic-electronic", "electronic")),
    ("electronica", ("electronic", "melodic-electronic")),
    ("nu disco", ("house-club", "electronic")),
    ("nu-disco", ("house-club", "electronic")),
    ("disco", ("jam-funk", "house-club")),
    # Bass / live electronic
    ("live electronic", ("bass-edm", "electronic", "jam-funk")),
    ("drum and bass", ("bass-edm", "electronic")),
    ("drum & bass", ("bass-edm", "electronic")),
    ("dnb", ("bass-edm", "electronic")),
    ("neurofunk", ("bass-edm", "electronic")),
    ("dubstep", ("bass-edm", "electronic")),
    ("brostep", ("bass-edm", "electronic")),
    ("riddim", ("bass-edm", "electronic")),
    ("glitch hop", ("bass-edm", "electronic")),
    ("moombahton", ("bass-edm", "electronic")),
    ("complextro", ("bass-edm", "electronic")),
    ("breakbeat", ("bass-edm", "electronic")),
    ("bass music", ("bass-edm", "electronic")),
    ("jungle", ("bass-edm", "electronic")),
    # Synth / indie dance
    ("synth pop", ("synth-indie-dance", "pop-rnb")),
    ("synth-pop", ("synth-indie-dance", "pop-rnb")),
    ("synthpop", ("synth-indie-dance", "pop-rnb")),
    ("electropop", ("synth-indie-dance", "pop-rnb", "electronic")),
    ("electro pop", ("synth-indie-dance", "pop-rnb", "electronic")),
    ("indie dance", ("synth-indie-dance", "electronic")),
    ("alternative dance", ("synth-indie-dance", "electronic")),
    ("dance punk", ("synth-indie-dance", "alt-indie")),
    ("dance-punk", ("synth-indie-dance", "alt-indie")),
    ("new wave", ("synth-indie-dance", "alt-indie")),
    ("synthwave", ("synth-indie-dance", "electronic")),
    ("darkwave", ("synth-indie-dance", "alt-indie")),
    ("indietronica", ("melodic-electronic", "synth-indie-dance", "electronic")),
    # Rock family
    ("classic rock", ("classic-hard-rock", "rock")),
    ("hard rock", ("classic-hard-rock", "rock")),
    ("blues rock", ("classic-hard-rock", "rock")),
    ("arena rock", ("classic-hard-rock", "rock")),
    ("album rock", ("classic-hard-rock", "rock")),
    ("southern rock", ("classic-hard-rock", "rock")),
    ("glam rock", ("classic-hard-rock", "rock")),
    ("hair metal", ("classic-hard-rock", "metal-punk", "rock")),
    ("rock and roll", ("classic-hard-rock", "rock")),
    ("rock & roll", ("classic-hard-rock", "rock")),
    ("soft rock", ("classic-hard-rock", "pop-rnb", "rock")),
    ("progressive rock", ("rock", "classic-hard-rock")),
    ("art rock", ("rock", "alt-indie")),
    ("psychedelic rock", ("rock", "jam-funk")),
    ("stoner rock", ("alt-indie", "rock", "metal-punk")),
    ("garage rock", ("alt-indie", "rock")),
    ("indie rock", ("alt-indie", "rock")),
    ("alternative rock", ("alt-indie", "rock")),
    ("alternative pop", ("alt-indie", "pop-rnb")),
    ("post grunge", ("alt-indie", "rock")),
    ("post-grunge", ("alt-indie", "rock")),
    ("grunge", ("alt-indie", "rock")),
    ("britpop", ("alt-indie", "pop-rnb", "rock")),
    ("shoegaze", ("alt-indie", "rock")),
    ("post punk", ("alt-indie", "rock")),
    ("post-punk", ("alt-indie", "rock")),
    ("college rock", ("alt-indie", "rock")),
    ("indie pop", ("alt-indie", "pop-rnb", "synth-indie-dance")),
    ("indie", ("alt-indie",)),
    ("alternative", ("alt-indie",)),
    ("pop rock", ("pop-rnb", "rock")),
    # Metal / punk
    ("progressive metal", ("metal-punk", "rock")),
    ("alternative metal", ("metal-punk", "alt-indie", "rock")),
    ("nu metal", ("metal-punk", "rock")),
    ("nu-metal", ("metal-punk", "rock")),
    ("heavy metal", ("metal-punk", "rock")),
    ("thrash metal", ("metal-punk", "rock")),
    ("death metal", ("metal-punk",)),
    ("black metal", ("metal-punk",)),
    ("doom metal", ("metal-punk",)),
    ("post-metal", ("metal-punk", "alt-indie")),
    ("metalcore", ("metal-punk",)),
    ("hardcore", ("metal-punk",)),
    ("post-hardcore", ("metal-punk", "alt-indie")),
    ("pop punk", ("metal-punk", "alt-indie")),
    ("pop-punk", ("metal-punk", "alt-indie")),
    ("punk rock", ("metal-punk", "rock")),
    ("ska punk", ("reggae-ska", "metal-punk", "rock")),
    ("ska-punk", ("reggae-ska", "metal-punk", "rock")),
    ("punk", ("metal-punk", "rock")),
    ("metal", ("metal-punk", "rock")),
    ("industrial", ("metal-punk", "electronic")),
    # Jam / funk
    ("jam band", ("jam-funk", "rock")),
    ("funk rock", ("jam-funk", "rock")),
    ("funk metal", ("jam-funk", "metal-punk")),
    ("p funk", ("jam-funk",)),
    ("jazz funk", ("jam-funk",)),
    ("acid jazz", ("jam-funk", "melodic-electronic")),
    ("neo psychedelia", ("jam-funk", "alt-indie")),
    ("funk", ("jam-funk",)),
    ("groove", ("jam-funk",)),
    ("jam", ("jam-funk",)),
    # Reggae / ska
    ("reggae rock", ("reggae-ska", "rock")),
    ("ska core", ("reggae-ska", "metal-punk")),
    ("skacore", ("reggae-ska", "metal-punk")),
    ("dancehall", ("reggae-ska",)),
    ("rocksteady", ("reggae-ska",)),
    ("reggae", ("reggae-ska",)),
    ("ska", ("reggae-ska",)),
    ("dub", ("reggae-ska", "electronic")),
    # Pop / R&B / soul
    ("contemporary r&b", ("pop-rnb",)),
    ("alternative r&b", ("pop-rnb", "alt-indie")),
    ("neo soul", ("pop-rnb",)),
    ("neo-soul", ("pop-rnb",)),
    ("quiet storm", ("pop-rnb",)),
    ("dance pop", ("pop-rnb", "electronic")),
    ("art pop", ("pop-rnb", "alt-indie")),
    ("adult contemporary", ("pop-rnb",)),
    ("singer songwriter", ("pop-rnb",)),
    ("r&b", ("pop-rnb",)),
    ("rnb", ("pop-rnb",)),
    ("soul", ("pop-rnb",)),
    # Folk / country absorbed into pop/rock rather than era bins
    ("folk rock", ("rock", "alt-indie")),
    ("americana", ("rock", "alt-indie")),
    ("country", ("rock",)),
    ("folk", ("alt-indie",)),
    # Catch-all parents last
    ("electro", ("electronic", "house-club")),
    ("dance", ("electronic", "house-club")),
    ("electronic", ("electronic",)),
    ("rock", ("rock",)),
    ("blues", ("classic-hard-rock", "jam-funk")),
    ("jazz", ("jam-funk",)),
    ("pop", ("pop-rnb",)),
)

_RULES_LONGEST_FIRST = tuple(sorted(_STYLE_RULES, key=lambda item: len(item[0]), reverse=True))


def normalize_label(value: str) -> str:
    text = (value or "").strip().casefold()
    text = text.replace("&", "and")
    text = text.replace("_", " ")
    text = text.replace("-", " ")
    text = re.sub(r"\s+", " ", text)
    return text


def is_meta_label(value: str) -> bool:
    label = normalize_label(value)
    if not label or label in META_LABELS:
        return True
    if ERA_RE.match(label.replace(" ", "")):
        return True
    return False


def labels_to_playlist_ids(labels: list[str]) -> set[str]:
    """Map raw genre/tag strings to overlapping style playlist ids."""
    usable = [normalize_label(label) for label in labels if not is_meta_label(label)]
    usable = [label for label in usable if label]
    if not usable:
        return set()

    matched: set[str] = set()
    consumed = [False] * len(usable)
    for key, playlist_ids in _RULES_LONGEST_FIRST:
        key_n = normalize_label(key)
        for index, label in enumerate(usable):
            if _token_match(label, key_n):
                matched.update(playlist_ids)
                consumed[index] = True

    strong = matched - {"pop-rnb", "electronic", "rock"}
    # Drop generic pop/dance/rock/electronic when they only appeared as exact
    # noisy tags and a more specific family already matched.
    if strong:
        generic_only = {normalize_label(label) for label, used in zip(usable, consumed) if used}
        if "pop" in usable and "pop" in generic_only:
            has_specific_pop = any(
                label != "pop" and "pop" in label.split() for label in usable
            )
            if not has_specific_pop and ("rock" in matched or "metal-punk" in matched or "hip-hop" in matched):
                matched.discard("pop-rnb")
    return matched


def map_artist_labels(genres: list[str], tags: list[str], fallback: list[str] | None = None) -> set[str]:
    combined = list(genres) + list(tags) + list(fallback or [])
    return labels_to_playlist_ids(combined)


def gb_name(name: str) -> str:
    if name.startswith(PLAYLIST_PREFIX):
        return name
    return f"{PLAYLIST_PREFIX}{name}"


def leftover_playlist() -> StylePlaylist:
    return PLAYLIST_BY_ID[LEFTOVER_ID]


def _token_match(label: str, key: str) -> bool:
    if label == key:
        return True
    label_parts = label.split()
    key_parts = key.split()
    n = len(key_parts)
    if n == 0 or n > len(label_parts):
        return False
    return any(label_parts[i : i + n] == key_parts for i in range(len(label_parts) - n + 1))
