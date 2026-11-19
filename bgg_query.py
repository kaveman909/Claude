#!/usr/bin/env python3
"""bgg_query - find the best BoardGameGeek games for a given player count.

Examples:
    python bgg_query.py "Best games at 6 players"
    python bgg_query.py "recommended games for 3" --top 300
    python bgg_query.py "best at 2 players" --user my_bgg_username
    python bgg_query.py "best at 5" --ids 174430,167791,224517

How it works:
  1. Builds a candidate list: BGG's top-ranked games (scraped from the
     browse pages), a user's collection (--user), or explicit IDs (--ids).
  2. Fetches each game's stats from the BGG XML API2, including the
     community "suggested number of players" poll.
  3. Ranks games by the share of voters who called that player count "Best"
     (or "Best"+"Recommended" when the query says "recommended").

BGG's XML API requires a registered application token. Get one at
https://boardgamegeek.com/applications and export it as BGG_TOKEN.
Only the Python standard library is used.
"""

import argparse
import os
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

API = "https://boardgamegeek.com/xmlapi2"
BROWSE = "https://boardgamegeek.com/browse/boardgame/page/{page}"
USER_AGENT = "bgg-query/1.0"
BATCH_SIZE = 20  # BGG caps /thing requests at 20 ids


# --------------------------------------------------------------------------- #
# Query parsing
# --------------------------------------------------------------------------- #

@dataclass
class Query:
    players: int
    mode: str = "best"  # "best" or "recommended"


def parse_query(text: str) -> Query:
    """Turn free text like 'Best games at 6 players' into a Query."""
    words = {
        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
        "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    }
    lowered = text.lower()
    match = re.search(r"\b(\d{1,2})\b", lowered)
    if match:
        players = int(match.group(1))
    else:
        found = [n for w, n in words.items() if re.search(rf"\b{w}\b", lowered)]
        if not found:
            raise ValueError(f"Couldn't find a player count in: {text!r}")
        players = found[0]
    if players < 1:
        raise ValueError("Player count must be at least 1")
    mode = "recommended" if re.search(r"\brecommend", lowered) or "good" in lowered else "best"
    return Query(players=players, mode=mode)


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #

def fetch(url: str, token: str | None = None, retries: int = 6) -> str:
    """GET a URL, retrying on BGG's 202 (queued) and 429/5xx (throttled)."""
    headers = {"User-Agent": USER_AGENT}
    if token and url.startswith(API):
        headers["Authorization"] = f"Bearer {token}"
    delay = 2.0
    for attempt in range(retries):
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                if resp.status == 202:  # collection request queued; try again
                    raise _Retry()
                return body
        except _Retry:
            pass
        except urllib.error.HTTPError as e:
            if e.code == 401:
                sys.exit("BGG rejected the request (401). Set BGG_TOKEN to a valid "
                         "application token from https://boardgamegeek.com/applications")
            if e.code not in (429, 500, 502, 503, 504) or attempt == retries - 1:
                raise
        time.sleep(delay)
        delay = min(delay * 2, 30)
    raise RuntimeError(f"Gave up fetching {url}")


class _Retry(Exception):
    pass


# --------------------------------------------------------------------------- #
# Candidate sources
# --------------------------------------------------------------------------- #

def top_ranked_ids(count: int) -> list[int]:
    """Scrape the IDs of BGG's top `count` ranked games (100 per page)."""
    ids: list[int] = []
    page = 1
    while len(ids) < count:
        html = fetch(BROWSE.format(page=page))
        page_ids = []
        for m in re.finditer(r'id=["\']results_objectname\d+["\'].*?href=["\']/boardgame/(\d+)/',
                             html, re.S):
            gid = int(m.group(1))
            if gid not in page_ids:
                page_ids.append(gid)
        if not page_ids:
            break
        ids.extend(page_ids)
        page += 1
        time.sleep(1)
    return ids[:count]


def collection_ids(user: str, token: str | None) -> list[int]:
    url = f"{API}/collection?username={urllib.request.quote(user)}&own=1&excludesubtype=boardgameexpansion"
    root = ET.fromstring(fetch(url, token))
    if root.tag == "errors":
        msg = root.findtext(".//message") or "unknown error"
        sys.exit(f"BGG collection error: {msg}")
    return [int(item.get("objectid")) for item in root.iter("item")]


# --------------------------------------------------------------------------- #
# Game data
# --------------------------------------------------------------------------- #

@dataclass
class Game:
    id: int
    name: str
    year: str
    min_players: int
    max_players: int
    rating: float
    rank: int | None
    # {"4": {"Best": 120, "Recommended": 40, "Not Recommended": 3}, "5+": {...}}
    poll: dict[str, dict[str, int]] = field(default_factory=dict)

    def votes_at(self, n: int) -> dict[str, int] | None:
        if str(n) in self.poll:
            return self.poll[str(n)]
        for key, votes in self.poll.items():  # "N+" bucket beyond the listed range
            if key.endswith("+") and n >= int(key[:-1]):
                return votes
        return None


def parse_things(xml_text: str) -> list[Game]:
    games = []
    root = ET.fromstring(xml_text)
    for item in root.iter("item"):
        if item.get("type") not in ("boardgame", None):
            continue
        name_el = item.find("name[@type='primary']")
        poll: dict[str, dict[str, int]] = {}
        poll_el = item.find("poll[@name='suggested_numplayers']")
        if poll_el is not None:
            for res in poll_el.findall("results"):
                poll[res.get("numplayers")] = {
                    r.get("value"): int(r.get("numvotes", 0)) for r in res.findall("result")
                }
        rank = None
        for r in item.findall("statistics/ratings/ranks/rank"):
            if r.get("name") == "boardgame" and r.get("value", "").isdigit():
                rank = int(r.get("value"))
        rating_el = item.find("statistics/ratings/average")
        games.append(Game(
            id=int(item.get("id")),
            name=name_el.get("value") if name_el is not None else "?",
            year=_attr(item, "yearpublished", "?"),
            min_players=int(_attr(item, "minplayers", "0") or 0),
            max_players=int(_attr(item, "maxplayers", "0") or 0),
            rating=float(rating_el.get("value")) if rating_el is not None else 0.0,
            rank=rank,
            poll=poll,
        ))
    return games


def _attr(item, tag, default):
    el = item.find(tag)
    return el.get("value", default) if el is not None else default


def fetch_games(ids: list[int], token: str | None, verbose: bool = True) -> list[Game]:
    games = []
    for i in range(0, len(ids), BATCH_SIZE):
        batch = ids[i:i + BATCH_SIZE]
        if verbose:
            print(f"  fetching games {i + 1}-{i + len(batch)} of {len(ids)}...", file=sys.stderr)
        url = f"{API}/thing?stats=1&id={','.join(map(str, batch))}"
        games.extend(parse_things(fetch(url, token)))
        time.sleep(1.5)  # be polite; BGG throttles aggressive clients
    return games


# --------------------------------------------------------------------------- #
# Ranking
# --------------------------------------------------------------------------- #

@dataclass
class Result:
    game: Game
    score: float  # fraction of voters at N who chose the target answer(s)
    best_pct: float
    rec_pct: float
    votes: int


def rank_games(games: list[Game], q: Query, min_votes: int) -> list[Result]:
    results = []
    for g in games:
        if not (g.min_players <= q.players <= g.max_players):
            continue
        v = g.votes_at(q.players)
        if not v:
            continue
        best, rec, notrec = v.get("Best", 0), v.get("Recommended", 0), v.get("Not Recommended", 0)
        total = best + rec + notrec
        if total < min_votes:
            continue
        best_pct, rec_pct = best / total, rec / total
        score = best_pct if q.mode == "best" else best_pct + rec_pct
        results.append(Result(g, score, best_pct, rec_pct, total))
    results.sort(key=lambda r: (r.score, r.game.rating), reverse=True)
    return results


def print_results(results: list[Result], q: Query, limit: int) -> None:
    label = "Best" if q.mode == "best" else "Best+Rec"
    print(f"\n{label} games at {q.players} players (by BGG community poll)\n")
    if not results:
        print("No matching games. Try --top with a larger number or lower --min-votes.")
        return
    header = f"{'#':>3}  {label:>8}  {'Best':>5}  {'Rec':>5}  {'Votes':>5}  {'Rating':>6}  {'Rank':>5}  Game"
    print(header)
    print("-" * len(header))
    for i, r in enumerate(results[:limit], 1):
        g = r.game
        print(f"{i:>3}  {r.score:>7.0%}  {r.best_pct:>5.0%}  {r.rec_pct:>5.0%}  {r.votes:>5}  "
              f"{g.rating:>6.2f}  {g.rank or '-':>5}  {g.name} ({g.year})  "
              f"[{g.min_players}-{g.max_players}p]")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main(argv=None) -> None:
    p = argparse.ArgumentParser(description="Find the best BGG games for a player count.")
    p.add_argument("query", help='e.g. "Best games at 6 players" or "recommended for 3"')
    src = p.add_mutually_exclusive_group()
    src.add_argument("--top", type=int, default=200,
                     help="search BGG's top N ranked games (default 200)")
    src.add_argument("--user", help="search this BGG user's owned collection instead")
    src.add_argument("--ids", help="comma-separated BGG game IDs to search instead")
    p.add_argument("--limit", type=int, default=15, help="how many results to show (default 15)")
    p.add_argument("--min-votes", type=int, default=20,
                   help="ignore games with fewer poll votes at that count (default 20)")
    p.add_argument("--token", default=os.environ.get("BGG_TOKEN"),
                   help="BGG API token (default: $BGG_TOKEN)")
    args = p.parse_args(argv)

    try:
        q = parse_query(args.query)
    except ValueError as e:
        p.error(str(e))

    if not args.token:
        print("warning: no BGG_TOKEN set; BGG's XML API will likely return 401.", file=sys.stderr)

    if args.ids:
        ids = [int(x) for x in args.ids.split(",") if x.strip()]
    elif args.user:
        print(f"Loading {args.user}'s collection...", file=sys.stderr)
        ids = collection_ids(args.user, args.token)
    else:
        print(f"Loading BGG top {args.top} ranked games...", file=sys.stderr)
        ids = top_ranked_ids(args.top)
    if not ids:
        sys.exit("No candidate games found.")

    games = fetch_games(ids, args.token)
    print_results(rank_games(games, q, args.min_votes), q, args.limit)


if __name__ == "__main__":
    main()
