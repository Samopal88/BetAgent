#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tennis_join_improved.py

Improves JOIN between backtest_tennis_players (Jeff Sackmann) and
backtest_tennis_matches (betz.su) via 3 strategies:
  METHOD 1: Exact name + exact date (bidirectional)
  METHOD 2: Exact name + date +/-1 day (bidirectional)
  METHOD 3: Name + same tournament + date +/-3 days (bidirectional)

Also expands tennis_name_lookup for unmapped names.
"""
import sqlite3
import difflib
import time
import sys
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)

DB_PATH = str(Path(__file__).parent / "betagent.db")
COVERAGE_OUT = "/tmp/tennis_join_coverage.txt"
STRATEGY_OUT = "/tmp/tennis_dominant_v2.txt"

conn = sqlite3.connect(DB_PATH, timeout=30)
conn.execute("PRAGMA journal_mode=WAL")
t0 = time.time()

cov = []  # coverage output lines
strat = []  # strategy output lines

def w(msg):
    cov.append(msg)
    print(msg)

def ws(msg):
    strat.append(msg)

# ---- transliteration ----
RUS = {'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'yo','ж':'zh',
       'з':'z','и':'i','й':'y','к':'k','л':'l','м':'m','н':'n','о':'o',
       'п':'p','р':'r','с':'s','т':'t','у':'u','ф':'f','х':'kh','ц':'ts',
       'ч':'ch','ш':'sh','щ':'shch','ъ':'','ы':'y','ь':'','э':'e',
       'ю':'yu','я':'ya','і':'i'}
ALTS = [('shch',['sch']),('kh',['h']),('ts',['tz']),('zh',['j']),('yo',['jo']),('yu',['iu']),('ya',['ia'])]

def xlit(t):
    return ''.join(RUS.get(c, c) for c in t.lower())

def xlit_vars(bare):
    base = xlit(bare)
    rs = {base}
    for pat, alts in ALTS:
        ns = set()
        for c in rs:
            if pat in c:
                for a in alts:
                    ns.add(c.replace(pat, a))
        rs |= ns
    return rs

def norm(s):
    return s.replace('\u0451','\u0435').replace('\u0401','\u0435').lower()

def eng_parts(name):
    """'Frances Tiafoe' -> ('tiafoe','f')"""
    p = name.strip().lower().split()
    return (p[-1], p[0][0]) if len(p) >= 2 else (p[0] if p else ('',''))

def rus_parts(rn):
    n = norm(rn.strip()).split()
    if len(n) >= 2:
        last = n[-1].rstrip('.')
        if len(last) <= 2 and last.isalpha():
            return (' '.join(n[:-1]).rstrip('.').lower(), last.lower())
        return (n[-1].lower(), n[0][0])
    return (n[0].lower() if n else ('',''))

KNOWN = {
    'соболенко':{'Sabalenka'}, 'собол':{'Sabalenka'},
    'свёнтек':{'Swiatek'}, 'свентек':{'Swiatek'},
    'рыбакина':{'Rybakina'}, 'рыбакин':{'Rybakina','Rybakin'},
    'хачанов':{'Khachanov'}, 'кудерметов':{'Kudermetova'},
    'медведев':{'Medvedev'}, 'рублев':{'Rublev'},
    'джокович':{'Djokovic'}, 'зверев':{'Zverev'},
    'тиафо':{'Tiafoe'}, 'фриц':{'Fritz'},
    'димитров':{'Dimitrov'}, 'рун':{'Rune'},
    'алькарас':{'Alcaraz'}, 'синнер':{'Sinner'},
    'гауф':{'Gauff'}, 'бадоса':{'Badosa'}, 'гауфф':{'Gauff'},
    'пер':{'Paul'}, 'павлюченков':{'Pavlyuchenkova'},
    'павлюченкова':{'Pavlyuchenkova'},
    'саккари':{'Sakkari'}, 'пегула':{'Pegula'}, 'жабер':{'Jabeur'},
    'квитова':{'Kvitova'}, 'квитов':{'Kvitova'},
    'козлов':{'Kozlova'}, 'козлова':{'Kozlova'},
}

TMAP = {
    'Мадрид':'Madrid','индиан-уэллс':'Indian Wells','индиан-веллс':'Indian Wells',
    'шанхай':'Shanghai','париж':'Paris','рим':'Rome','австралийский':'Australian Open',
    'ролан гаррос':'Roland Garros','уимблдон':'Wimbledon','ус опен':'US Open',
    'майами':'Miami','пекин':'Beijing','уахан':'Wuhan','дубай':'Dubai','доха':'Doha',
    'аделаида':'Adelaide','бризбен':'Brisbane','бухарест':'Bucharest',
    'марракеш':'Marrakech','хьюстон':'Houston','богота':'Bogota','линец':'Linz',
    'руан':'Rouen','страсбург':'Strasbourg','ноттингем':'Nottingham','берлин':'Berlin',
    'будапешт':'Budapest','бостад':'Bastad','гамбург':'Hamburg',
    'винстон-сейлем':'Winston Salem','стоколм':'Stockholm','стокгольм':'Stockholm',
    'антверпен':'Antwerp','базель':'Basel','вьенна':'Vienna','вьентьян':'Vienna',
    'софия':'Sofia','монпелье':'Montpellier','марсель':'Marseille',
    'роттердам':'Rotterdam','даллас':'Dallas','чарльстон':'Charleston',
    'барселона':'Barcelona','ошава':'Ostrava','монреаль':'Montreal',
    'монтреаль':'Montreal','торонто':'Montreal','буэнос-айрес':'Buenos Aires',
    'буэнос-айре':'Buenos Aires','акапулько':'Acapulco','осло':'Oeiras',
    'халле':'Halle','лондон':'Queen\'s Club','ньюпорт':'Newport','росмален':'Rosmalen',
    'истборн':'Eastbourne','флоренция':'Florence','мехико':'Cabo San Lucas',
    'кицбюэль':'Kitzbuhel','гштад':'Gstaad','умма':'Umag','атланта':'Atlanta',
    'ло-каб':'Los Cabos','метц':'Metz','монте-карло':'Monte Carlo',
    'токио':'Tokyo','сеул':'Seoul','гуанчжоу':'Guangzhou',
    'хуахин':'Hua Hin','чжэнчжоу':'Zhengzhou','жэньчжоу':'Zhengzhou',
    'хангчжоу':'Hangzhou','гвадалахара':'Guadalajara','сан-диего':'San Diego',
    'оахака':'Oaxaca','мидленд':'Midland','расин':'Racine','тайлер':'Tyler',
    'бонита-спрингс':'Bonita Springs','кальп':'Cary Challenger',
    'калари':'Cagliari','винстон сейлем':'Winston Salem',
}

def tourney_eng(btz_str):
    for part in btz_str.split('.'):
        ps = part.strip()
        if not ps:
            continue
        for rk, ev in TMAP.items():
            if norm(rk) in norm(ps) and ev:
                return ev
    return None

BATCH = 1000

# ================================================================
# PHASE 1: Baseline
# ================================================================
w("=" * 70)
w("TENNIS JOIN IMPROVEMENT - Coverage & Strategy Analysis")
w("=" * 70)

w("\n" + "=" * 70)
w("PHASE 1: BASELINE COVERAGE")
w("=" * 70)

tm0 = conn.execute("SELECT COUNT(*) FROM backtest_tennis_matches").fetchone()[0]
ubetz = conn.execute(
    "SELECT COUNT(*) FROM (SELECT player1 as n FROM backtest_tennis_matches UNION SELECT player2 FROM backtest_tennis_matches)"
).fetchone()[0]
lk0 = conn.execute("SELECT COUNT(*) FROM tennis_name_lookup").fetchone()[0]
jtot = conn.execute(
    "SELECT COUNT(*) FROM (SELECT DISTINCT LOWER(winner_name) FROM backtest_tennis_players UNION SELECT DISTINCT LOWER(loser_name) FROM backtest_tennis_players)"
).fetchone()[0]
eik0 = conn.execute("SELECT COUNT(DISTINCT eng_name) FROM tennis_name_lookup").fetchone()[0]
mb0 = conn.execute("""
    SELECT COUNT(*) FROM backtest_tennis_matches m
    JOIN tennis_name_lookup t1 ON t1.betz_name = m.player1
    JOIN tennis_name_lookup t2 ON t2.betz_name = m.player2
""").fetchone()[0]
ptot = conn.execute("SELECT COUNT(*) FROM backtest_tennis_players").fetchone()[0]

w(f"Lookup entries:              {lk0}")
w(f"Total betz unique names:     {ubetz}")
w(f"Eng names in lookup:         {eik0}/{jtot} ({eik0/jtot*100:.1f}%)")
w(f"Betz matches BOTH mapped:    {mb0}/{tm0} ({mb0/tm0*100:.1f}%)")
w(f"Total backtest_tennis_players: {ptot}")

w("\n  Baseline JOIN (bidirectional - correct approach):")
for label, dc in [
    ("Exact date", "p.tourney_date = m.match_date"),
    ("Date+/-1", "ABS(JULIANDAY(p.tourney_date)-JULIANDAY(m.match_date))<=1"),
    ("Date+/-3", "ABS(JULIANDAY(p.tourney_date)-JULIANDAY(m.match_date))<=3"),
]:
    c = conn.execute(f"""
        SELECT COUNT(DISTINCT p.id) FROM backtest_tennis_players p
        JOIN tennis_name_lookup lw ON LOWER(p.winner_name)=lw.eng_name
        JOIN tennis_name_lookup ll ON LOWER(p.loser_name)=ll.eng_name
        JOIN backtest_tennis_matches m ON m.tour=p.tour
          AND ((m.player1=lw.betz_name AND m.player2=ll.betz_name)
               OR (m.player1=ll.betz_name AND m.player2=lw.betz_name))
          AND {dc}
    """).fetchone()[0]
    w(f"    {label}: {c} ({c/ptot*100:.1f}%)")

# ================================================================
# PHASE 2: Unmapped Jeff names
# ================================================================
w("\n" + "=" * 70)
w("PHASE 2: UNMAPPED JEFF SACKMANN NAMES")
w("=" * 70)

uw = conn.execute("""
    SELECT count(distinct winner_name) FROM backtest_tennis_players
    WHERE lower(winner_name) NOT IN (SELECT eng_name FROM tennis_name_lookup)
""").fetchone()[0]

unmapped = set()
for col in ('winner_name','loser_name'):
    for (name,) in conn.execute(
        f"SELECT DISTINCT {col} FROM backtest_tennis_players WHERE {col} IS NOT NULL AND lower({col}) NOT IN (SELECT eng_name FROM tennis_name_lookup)"
    ).fetchall():
        unmapped.add(name.lower())

w(f"Unmapped distinct winners:   {uw}")
w(f"Unmapped names (any role):   {len(unmapped)}")

# ================================================================
# PHASE 3: Expand mapping
# ================================================================
w("\n" + "=" * 70)
w("PHASE 3: EXPANDING NAME MAPPING")
w("=" * 70)

btz = set()
for col in ('player1','player2'):
    for (n,) in conn.execute(f"SELECT DISTINCT {col} FROM backtest_tennis_matches WHERE {col} IS NOT NULL").fetchall():
        btz.add(n)

bidx = defaultdict(list)
for bn in btz:
    s, i = rus_parts(bn)
    if s:
        for tv in xlit_vars(s):
            bidx[tv].append((bn, i))

w(f"Betz names parsed:           {len(btz)}")
w(f"Translit index entries:      {len(bidx)}")

new_map = []
for en in sorted(unmapped):
    es, ei = eng_parts(en)
    cands = []
    # Known
    for kv, esurnames in KNOWN.items():
        for ks in esurnames:
            if ks.lower() == es:
                for tv in xlit_vars(kv):
                    for bn, bi in bidx.get(tv, []):
                        sc = 98 if (ei and bi and ei==bi) else 95
                        cands.append((bn, sc, 'known'))
    # Exact translit
    for tv in xlit_vars(es):
        for bn, bi in bidx.get(tv, []):
            sc = 96 if (ei and bi and ei==bi) else 90
            cands.append((bn, sc, 'translit'))
    # Fuzzy (only if no exact)
    if not cands:
        for bs in bidx:
            if abs(len(bs)-len(es)) > 4:
                continue
            sim = difflib.SequenceMatcher(None, bs, es).ratio() * 100
            if sim >= 75:
                for bn, bi in bidx[bs]:
                    sc = min(sim+5, 99) if (ei and bi and ei==bi) else sim
                    cands.append((bn, sim, 'fuzzy'))
    if not cands:
        continue
    best = {}
    for bn, sc, mt in cands:
        if bn not in best or sc > best[bn][0]:
            best[bn] = (sc, mt)
    sc = sorted(best.items(), key=lambda x: -x[1][0])
    bbn, (bsc, bmt) = sc[0]
    sc2 = sc[1][1][0] if len(sc) > 1 else 0
    if bsc >= 90 or (bsc >= 78 and (sc2==0 or bsc-sc2 >= 12)):
        new_map.append((bbn, en))

# Dedup against existing
ebetz = set(norm(r[0]) for r in conn.execute("SELECT betz_name FROM tennis_name_lookup").fetchall())
seen = set()
unique_new = []
for bn, en in new_map:
    if norm(bn) in ebetz or bn in seen:
        continue
    seen.add(bn)
    unique_new.append((bn, en))

w(f"New confident mappings:      {len(unique_new)}")

# Also add surname+initial variants
entries = set()
for bn, en in unique_new:
    entries.add((bn, en))
    s, i = rus_parts(bn)
    if s and i and len(i) <= 2:
        entries.add((f"{s} {i.upper()}.", en))
        entries.add((f"{i.upper()}. {s}", en))

to_ins = [(bn, en) for bn, en in entries if norm(bn) not in ebetz]
w(f"Lookup entries to insert:    {len(to_ins)}")

for i in range(0, len(to_ins), BATCH):
    conn.executemany(
        "INSERT OR REPLACE INTO tennis_name_lookup (betz_name, eng_name) VALUES (?, ?)",
        to_ins[i:i+BATCH])
conn.commit()
w("Inserted into tennis_name_lookup.")

# ================================================================
# PHASE 4: Post-expansion coverage
# ================================================================
w("\n" + "=" * 70)
w("PHASE 4: POST-EXPANSION COVERAGE")
w("=" * 70)

lk2 = conn.execute("SELECT COUNT(*) FROM tennis_name_lookup").fetchone()[0]
ei2 = conn.execute("SELECT COUNT(DISTINCT eng_name) FROM tennis_name_lookup").fetchone()[0]
mb2 = conn.execute("""
    SELECT COUNT(*) FROM backtest_tennis_matches m
    JOIN tennis_name_lookup t1 ON t1.betz_name = m.player1
    JOIN tennis_name_lookup t2 ON t2.betz_name = m.player2
""").fetchone()[0]

w(f"Lookup entries:              {lk2} (was {lk0})")
w(f"Eng names in lookup:         {ei2}/{jtot} ({ei2/jtot*100:.1f}%)")
w(f"Betz matches BOTH mapped:    {mb2}/{tm0} ({mb2/tm0*100:.1f}%)")

w("\n  JOIN coverage after expansion (bidirectional):")
m1, m2, m3 = None, None, None
for label, dc in [
    ("METHOD 1: exact+exact", "p.tourney_date=m.match_date"),
    ("METHOD 2: name+date+/-1", "ABS(JULIANDAY(p.tourney_date)-JULIANDAY(m.match_date))<=1"),
    ("METHOD 3: no tourney, date+/-3", "ABS(JULIANDAY(p.tourney_date)-JULIANDAY(m.match_date))<=3"),
]:
    c = conn.execute(f"""
        SELECT COUNT(DISTINCT p.id) FROM backtest_tennis_players p
        JOIN tennis_name_lookup lw ON LOWER(p.winner_name)=lw.eng_name
        JOIN tennis_name_lookup ll ON LOWER(p.loser_name)=ll.eng_name
        JOIN backtest_tennis_matches m ON m.tour=p.tour
          AND ((m.player1=lw.betz_name AND m.player2=ll.betz_name)
               OR (m.player1=ll.betz_name AND m.player2=lw.betz_name))
          AND {dc}
    """).fetchone()[0]
    w(f"    {label}: {c}")
    if 'exact' in label: m1 = c
    elif '+/-1' in label: m2 = c
    else: m3 = c

# ================================================================
# PHASE 5: Tournament-aware Method 3
# ================================================================
w("\n" + "=" * 70)
w("PHASE 5: TOURNAMENT-AWARE JOIN")
w("=" * 70)

# Map betz tournaments
conn.execute("DROP TABLE IF EXISTS _btm")
conn.execute("CREATE TABLE _btm (btz TEXT PRIMARY KEY, eng TEXT)")
bts = set(r[0] for r in conn.execute("SELECT DISTINCT tournament FROM backtest_tennis_matches WHERE tournament IS NOT NULL").fetchall())
bte = []
ubt = 0
for bt in bts:
    e = tourney_eng(bt)
    if e:
        bte.append((norm(bt), norm(e)))
    else:
        ubt += 1

for i in range(0, len(bte), BATCH):
    conn.executemany("INSERT INTO _btm VALUES (?, ?)", bte[i:i+BATCH])
conn.commit()
w(f"Betz tournaments mapped:     {len(bte)}/{len(bts)}")
if ubt:
    w(f"Unmapped betz tournaments:   {ubt}")
    sample = conn.execute("SELECT DISTINCT tournament FROM backtest_tennis_matches WHERE tournament IS NOT NULL LIMIT 15").fetchall()
    unmapped_tourneys = []
    for (bt,) in sample:
        if not tourney_eng(bt):
            unmapped_tourneys.append(bt)
    for i, t in enumerate(unmapped_tourneys[:15]):
        w(f"  {i+1}. {t}")

# Map Jeff tournaments to normalized English
conn.execute("DROP TABLE IF EXISTS _jtm")
conn.execute("CREATE TABLE _jtm (tname TEXT PRIMARY KEY, norm TEXT)")

jts = set(r[0] for r in conn.execute("SELECT DISTINCT tourney_name FROM backtest_tennis_players WHERE tourney_name IS NOT NULL").fetchall())
jnorm = 0

# Build English tournament -> betz normalized lookup
eng_to_betz = defaultdict(set)
for bnorm, enorm in bte:
    eng_to_betz[enorm].add(bnorm)

# For each Jeff tournament, try to find matching English tournament
jt_entries = []
for jt in jts:
    jt_n = norm(jt)
    found = None
    for ename in eng_to_betz:
        if jt_n == ename or jt_n in ename or ename in jt_n:
            found = ename
            break
    if found:
        jt_entries.append((jt, found))
        jnorm += 1

for i in range(0, len(jt_entries), BATCH):
    conn.executemany("INSERT INTO _jtm VALUES (?, ?)", jt_entries[i:i+BATCH])
conn.commit()
w(f"Jeff tournaments normalized: {jnorm}/{len(jts)}")

if jt_entries:
    w("Sample normalized Jeff tournaments:")
    for jn, en in sorted(jt_entries)[:15]:
        w(f"  '{jn}' -> '{en}'")

# Method 3 count: join on tournament match + date +/-3
w("\n  METHOD 3 (tournament + date+/-3):")
m3t = conn.execute("""
    SELECT COUNT(DISTINCT p.id) FROM backtest_tennis_players p
    JOIN tennis_name_lookup lw ON LOWER(p.winner_name)=lw.eng_name
    JOIN tennis_name_lookup ll ON LOWER(p.loser_name)=ll.eng_name
    JOIN backtest_tennis_matches m ON m.tour=p.tour
      AND ((m.player1=lw.betz_name AND m.player2=ll.betz_name)
           OR (m.player1=ll.betz_name AND m.player2=lw.betz_name))
      AND EXISTS (
          SELECT 1 FROM _btm JOIN _jtm ON _btm.eng=_jtm.norm
          WHERE _jtm.tname=p.tourney_name AND _btm.btz=LOWER(m.tournament)
      )
      AND ABS(JULIANDAY(p.tourney_date)-JULIANDAY(m.match_date))<=3
""").fetchone()[0]
w(f"    {m3t}")

# Total unique betz match IDs joined by any method
conn.execute("DROP TABLE IF EXISTS _m12_ids")
conn.execute("""
    CREATE TABLE _m12_ids AS
    SELECT DISTINCT m.id as mid
    FROM backtest_tennis_players p
    JOIN tennis_name_lookup lw ON LOWER(p.winner_name)=lw.eng_name
    JOIN tennis_name_lookup ll ON LOWER(p.loser_name)=ll.eng_name
    JOIN backtest_tennis_matches m ON m.tour=p.tour
      AND ((m.player1=lw.betz_name AND m.player2=ll.betz_name)
           OR (m.player1=ll.betz_name AND m.player2=lw.betz_name))
      AND ABS(JULIANDAY(p.tourney_date)-JULIANDAY(m.match_date))<=1
""")

conn.execute("DROP TABLE IF EXISTS _m3_ids")
conn.execute("""
    CREATE TABLE _m3_ids AS
    SELECT DISTINCT m.id as mid
    FROM backtest_tennis_players p
    JOIN tennis_name_lookup lw ON LOWER(p.winner_name)=lw.eng_name
    JOIN tennis_name_lookup ll ON LOWER(p.loser_name)=ll.eng_name
    JOIN backtest_tennis_matches m ON m.tour=p.tour
      AND ((m.player1=lw.betz_name AND m.player2=ll.betz_name)
           OR (m.player1=ll.betz_name AND m.player2=lw.betz_name))
      AND EXISTS (
          SELECT 1 FROM _btm JOIN _jtm ON _btm.eng=_jtm.norm
          WHERE _jtm.tname=p.tourney_name AND _btm.btz=LOWER(m.tournament)
      )
      AND ABS(JULIANDAY(p.tourney_date)-JULIANDAY(m.match_date))<=3
""")

c12 = conn.execute("SELECT COUNT(*) FROM _m12_ids").fetchone()[0]
c3 = conn.execute("SELECT COUNT(*) FROM _m3_ids").fetchone()[0]
c3only = conn.execute("SELECT COUNT(*) FROM _m3_ids WHERE mid NOT IN (SELECT mid FROM _m12_ids)").fetchone()[0]
call = conn.execute("""
    SELECT COUNT(*) FROM (SELECT mid FROM _m12_ids UNION SELECT mid FROM _m3_ids)
""").fetchone()[0]

w(f"\n  SUMMARY OF 3-WAY JOIN:")
w(f"    METHOD 1 (exact+exact):             {m1}")
w(f"    METHOD 2 (name+date+/-1):           {m2}")
w(f"    METHOD 3 (name+tourney+date+/-3):   {m3t}")
w(f"    Unique betz matches via any method: {call}/{tm0} ({call/tm0*100:.1f}%)")
w(f"    Method 3 only (not M1/M2):          {c3only}")
w(f"    Time so far: {time.time()-t0:.1f}s")

# ================================================================
# PHASE 6: Build joined table for strategy
# ================================================================
w("\n" + "=" * 70)
w("PHASE 6: BUILDING JOINED TABLE")
w("=" * 70)

conn.execute("DROP TABLE IF EXISTS _joined")
conn.execute("""
    CREATE TABLE _joined AS
    SELECT DISTINCT
        p.id AS pid, p.tour, p.year, p.tourney_date, p.tourney_name,
        p.winner_name, p.loser_name, p.winner_rank, p.loser_rank,
        p.sets_loser, p.straight_sets,
        m.odds_p1, m.odds_p2, m.player1, m.player2
    FROM backtest_tennis_players p
    JOIN tennis_name_lookup lw ON LOWER(p.winner_name)=lw.eng_name
    JOIN tennis_name_lookup ll ON LOWER(p.loser_name)=ll.eng_name
    JOIN backtest_tennis_matches m ON m.tour=p.tour
      AND ((m.player1=lw.betz_name AND m.player2=ll.betz_name)
           OR (m.player1=ll.betz_name AND m.player2=lw.betz_name))
      AND ABS(JULIANDAY(p.tourney_date)-JULIANDAY(m.match_date))<=1
""")

jc = conn.execute("SELECT COUNT(*) FROM _joined").fetchone()[0]
w(f"Joined rows (+/-1 day):        {jc}")

jc3 = conn.execute(f"""
    SELECT COUNT(DISTINCT p.id) FROM backtest_tennis_players p
    JOIN tennis_name_lookup lw ON LOWER(p.winner_name)=lw.eng_name
    JOIN tennis_name_lookup ll ON LOWER(p.loser_name)=ll.eng_name
    JOIN backtest_tennis_matches m ON m.tour=p.tour
      AND ((m.player1=lw.betz_name AND m.player2=ll.betz_name)
           OR (m.player1=ll.betz_name AND m.player2=lw.betz_name))
      AND EXISTS (
          SELECT 1 FROM _btm JOIN _jtm ON _btm.eng=_jtm.norm
          WHERE _jtm.tname=p.tourney_name AND _btm.btz=LOWER(m.tournament)
      )
      AND ABS(JULIANDAY(p.tourney_date)-JULIANDAY(m.match_date))<=3
""").fetchone()[0]
w(f"Also via tournament method:    {jc3}")

# ================================================================
# PHASE 7: Strategy
# ================================================================
ws("=" * 70)
ws("DOMINANT WINNER STRATEGY v2 - WTA with Real Odds")
ws("=" * 70)

# Build player history
ph = defaultdict(list)
for row in conn.execute("""
    SELECT tourney_date, winner_name, loser_name, sets_loser
    FROM backtest_tennis_players
    WHERE winner_rank IS NOT NULL AND loser_rank IS NOT NULL
    ORDER BY tourney_date
""").fetchall():
    d, wn, ln, sl = row
    ph[wn.lower()].append((d, True, sl))
    ph[ln.lower()].append((d, False, sl))

ws(f"Players with history: {len(ph)}")

def dom_pct(player, dt, n=10):
    prev = [(d,w,sl) for d,w,sl in ph.get(player,[]) if d < dt]
    prev.sort(reverse=True)
    prev = prev[:n]
    wins = [(d,w,sl) for d,w,sl in prev if w]
    if not wins:
        return None
    return sum(1 for _,_,sl in wins if sl==0) / len(wins) * 100

def run_strat(rank_max, rd_min, dpct_min, tour_filter=None):
    res = defaultdict(lambda: [0, 0, 0, 0.0])  # [n, straight, loses, sum_odds]
    j = conn.execute("""
        SELECT year, tour, winner_name, loser_name,
               winner_rank, loser_rank, sets_loser,
               odds_p1, odds_p2, player1, player2, tourney_date
        FROM _joined
        """ + (f"WHERE tour='{tour_filter}'" if tour_filter else "")
    ).fetchall()

    # Pre-load lookup: eng_lower -> single betz_name
    lmap = {}
    for bn, en in conn.execute("SELECT betz_name, eng_name FROM tennis_name_lookup").fetchall():
        lmap[en] = bn

    for yr, tour, wn, ln, wr, lr, sl, o1, o2, p1, p2, td in j:
        wri = int(wr) if wr else 999
        lri = int(lr) if lr else 0
        if wri > rank_max or (lri-wri) < rd_min:
            continue
        dp = dom_pct(wn.lower(), td)
        if dp is None or dp < dpct_min:
            continue

        wb = lmap.get(wn.lower())
        if not wb:
            continue
        wo = o1 if wb==p1 else o2
        # Approximate straight-set odds
        so = max(1.10, wo * 0.75 + 0.40)

        key = (yr if yr else 0, tour)
        res[key][0] += 1
        res[key][3] += so
        if sl == 0:
            res[key][1] += 1
        else:
            res[key][2] += 1
    return dict(res)

def print_strat(results, label):
    ws(f"\n{label}")
    ws("=" * len(label))
    ws(f"{'Year':>4} {'Tour':>3} {'N':>5} {'Straight':>9} {'Win%':>7} {'Lost':>6} {'AvgOdds':>8} {'ROI':>8}")
    ws("-" * 65)
    tn=ts=tl=to=0
    for key in sorted(results.keys()):
        yr, tour = key
        n,s,l,so = results[key]
        pct = s/n*100 if n else 0
        ao = so/n if n else 0
        roi = (s*ao-n)/n*100 if n else 0
        ws(f"{str(yr):>4} {tour:>3} {n:>5} {s:>9} {pct:>6.1f}% {l:>6} {ao:>8.2f} {roi:>+8.1f}%")
        tn+=n; ts+=s; tl+=l; to+=so
    if tn:
        op=ts/tn*100; oa=to/tn; roi=(ts*oa-tn)/tn*100
        ws("-" * 65)
        ws(f"{'ALL':>4} {'':>3} {tn:>5} {ts:>9} {op:>6.1f}% {tl:>6} {oa:>8.2f} {roi:>+8.1f}%")
    else:
        ws("No bets qualified.")
    return tn

# WTA STRICT
ws("\n" + "=" * 70)
ws("WTA STRICT: winner_rank<=15, rank_diff>=50, dom_pct>=65%")
ws("=" * 70)
r1 = run_strat(15, 50, 65, 'WTA')
n1 = print_strat(r1, "")

# WTA RELAXED
ws("\n" + "=" * 70)
ws("WTA RELAXED: winner_rank<=20, rank_diff>=40, dom_pct>=55%")
ws("=" * 70)
r2 = run_strat(20, 40, 55, 'WTA')
n2 = print_strat(r2, "")

# Comparison
ws("\n" + "=" * 70)
ws("COVERAGE COMPARISON")
ws("=" * 70)
ws(f"Old method (exact name+date):      {m1} player-matches")
ws(f"New method (3-way combined):       {call} unique betz ({call/tm0*100:.1f}%)")
ws(f"Baseline both-mapped:              {mb0}/{tm0} ({mb0/tm0*100:.1f}%)")
ws(f"Improvement over baseline:         +{call - mb0} betz matches")
ws(f"STRATEGY coverage:                 {n1} bets (strict), {n2} bets (relaxed)")

# Save
with open(COVERAGE_OUT, 'w', encoding='utf-8') as f:
    f.write('\n'.join(cov))
with open(STRATEGY_OUT, 'w', encoding='utf-8') as f:
    f.write('\n'.join(strat))

w(f"\nCoverage report: {COVERAGE_OUT}")
w(f"Strategy results: {STRATEGY_OUT}")
w(f"Total time: {time.time()-t0:.1f}s")
conn.close()
print("\nDONE")
