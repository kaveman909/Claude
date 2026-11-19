import sys, os, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import bgg_query as b

def item(gid, name, minp, maxp, avg, rank, poll):
    res = "".join(
        f'<results numplayers="{n}"><result value="Best" numvotes="{v[0]}"/>'
        f'<result value="Recommended" numvotes="{v[1]}"/>'
        f'<result value="Not Recommended" numvotes="{v[2]}"/></results>' for n, v in poll.items())
    return f'''<item type="boardgame" id="{gid}"><name type="primary" sortindex="1" value="{name}"/>
<yearpublished value="2015"/><minplayers value="{minp}"/><maxplayers value="{maxp}"/>
<poll name="suggested_numplayers" title="User Suggested Number of Players" totalvotes="1">{res}</poll>
<statistics page="1"><ratings><average value="{avg}"/><ranks>
<rank type="subtype" id="1" name="boardgame" friendlyname="Board Game Rank" value="{rank}" bayesaverage="7"/>
</ranks></ratings></statistics></item>'''

XML = "<items>" + item(1, "Party Game", 3, 8, 7.0, 300, {"5": (50, 40, 5), "6": (90, 20, 5), "6+": (10, 10, 10)}) \
    + item(2, "Heavy Euro", 1, 6, 8.5, 5, {"4": (200, 50, 5), "6": (5, 60, 100)}) \
    + item(3, "Duel Game", 2, 2, 8.0, 20, {"2": (500, 10, 1)}) \
    + item(4, "Big Group", 4, 10, 7.5, 150, {"6": (70, 30, 2), "7+": (40, 20, 5)}) + "</items>"

class T(unittest.TestCase):
    def test_parse_query(self):
        self.assertEqual(b.parse_query("Best games at 6 players"), b.Query(6, "best"))
        self.assertEqual(b.parse_query("recommended games for three"), b.Query(3, "recommended"))
        with self.assertRaises(ValueError): b.parse_query("best games")

    def test_parse_things(self):
        g = {x.id: x for x in b.parse_things(XML)}
        self.assertEqual(g[2].name, "Heavy Euro"); self.assertEqual(g[2].rank, 5)
        self.assertEqual(g[1].poll["6"]["Best"], 90)
        self.assertEqual(g[4].votes_at(9)["Best"], 40)  # falls into 7+ bucket

    def test_rank_best_at_6(self):
        r = b.rank_games(b.parse_things(XML), b.Query(6), min_votes=20)
        self.assertEqual([x.game.name for x in r], ["Party Game", "Big Group", "Heavy Euro"])

    def test_player_range_filter(self):
        r = b.rank_games(b.parse_things(XML), b.Query(2), min_votes=1)
        self.assertEqual([x.game.name for x in r], ["Duel Game"])

    def test_browse_scrape(self):
        html = '''<td id="results_objectname1"><a href="/boardgame/224517/brass-birmingham">Brass</a></td>
                  <td id='results_objectname2'><a href='/boardgame/161936/pandemic-legacy'>PL</a></td>'''
        orig = b.fetch
        b.fetch = lambda url, token=None: html if "page/1" in url else ""
        try: self.assertEqual(b.top_ranked_ids(5), [224517, 161936])
        finally: b.fetch = orig

if __name__ == "__main__": unittest.main()
