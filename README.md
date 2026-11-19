# bgg_query

Ask BoardGameGeek things like **"Best games at 6 players"** from the command line.

It ranks games by BGG's community *Suggested Number of Players* poll: the share of voters who said that player count is **Best**. If your query says "recommended", it uses Best + Recommended instead.

## Setup

BGG's XML API needs a free application token. Register one at <https://boardgamegeek.com/applications>, then:

```bash
export BGG_TOKEN=your-token-here
```

It needs Python 3.10+ and nothing else.

## Usage

```bash
python bgg_query.py "Best games at 6 players"              # searches BGG's top 200
python bgg_query.py "best at 4" --top 500 --limit 25       # search wider, show more
python bgg_query.py "recommended games for 3"              # Best + Recommended
python bgg_query.py "best at 2 players" --user YOUR_BGG_NAME   # just your collection
python bgg_query.py "best at 5" --ids 174430,167791,224517     # specific games
```

| Option | Meaning |
|---|---|
| `--top N` | Candidates are BGG's top N ranked games (default 200) |
| `--user NAME` | Candidates are the games that user owns |
| `--ids a,b,c` | Candidates are these BGG IDs |
| `--limit N` | Number of results to show (default 15) |
| `--min-votes N` | Skip games with fewer poll votes at that count (default 20) |

## Tests

```bash
python -m unittest discover tests
```
