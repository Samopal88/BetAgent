#!/usr/bin/env python3
"""Tennis strategy analysis v3 - fixed."""
import sqlite3, re, math
from itertools import product
from collections import defaultdict

DB = "betagent.db"

def get_total_games(score):
    if not score: return 0
    return sum(int(n) for n in re.findall(r'\d+', score))

def get_surface(row):
    s = row.get('surface','')
    if s and str(s).strip(): return str(s).strip()
    if 'Clay' in str(row.get('tournament','')): return 'clay'
    return 'hard'

def odds_band(o):
    if o < 1.30: return '<1.30'
    if o < 1.40: return '1.30-1.40'
    if o < 1.50: return '1.40-1.50'
    if o < 1.70: return '1.50-1.70'
    if o < 2.00: return '1.70-2.00'
    return '>=2.00'

def calc_stats(matches, key_fn=None):
    """Compute stats from matches. key_fn converts match -> (hit, odds, yr)."""
    data = []
    for m in matches:
        hit, odds, yr = key_fn(m)
        data.append({'hit':hit,'odds':odds,'yr':yr})
    return _stats(data)

def _stats(data):
    n = len(data)
    if n < 50: return None
    hits = sum(1 for d in data if d['hit'])
    profit = sum(d['odds']-1 if d['hit'] else -1 for d in data)
    roi = profit/n*100
    pct = hits/n*100
    max_l = cs = 0
    for d in data:
        if not d['hit']: cs += 1; max_l = max(max_l,cs)
        else: cs = 0
    return {'n':n,'hits':hits,'win_pct':round(pct,1),'roi':round(roi,2),'max_lose':max_l}

def yr_breakdown(matches, key_fn):
    """Per-year stats."""
    by_yr = {}
    for yr in ['2021','2022','2023','2024']:
        yr_m = [m for m in matches if m['yr']==yr]
        by_yr[yr] = calc_stats(yr_m, key_fn)
    return by_yr

# Load
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()
cur.execute("""
    SELECT * FROM backtest_tennis_matches
    WHERE sets_winner IS NOT NULL AND odds_p1 IS NOT NULL AND odds_p2 IS NOT NULL
      AND strftime('%Y', match_date) IN ('2021','2022','2023','2024')
""")
rows = []
for r in cur.fetchall():
    d = dict(r)
    d['yr'] = d['match_date'][:4]
    d['surf'] = get_surface(d)
    d['tg'] = get_total_games(d.get('score_detail'))
    d['fav_odds'] = d['odds_p1'] if d['odds_p1'] < d['odds_p2'] else d['odds_p2']
    d['fav_won'] = 1 if (d['odds_p1'] < d['odds_p2'] and d['sets_winner'] > d['sets_loser']) or \
                         (d['odds_p2'] < d['odds_p1'] and d['sets_loser'] > d['sets_winner']) else 0
    rows.append(d)
print(f"Loaded {len(rows)} matches | clay={sum(1 for r in rows if r['surf']=='clay')} hard={sum(1 for r in rows if r['surf']=='hard')}")

# ================================================================
# 1) FAVORITE WINS — surface x tour x level x odds_band
print("\n" + "="*90)
print("1) FAVORITE WINS — surface x tour x level x odds_band")
print("="*90)
F1 = []
for surf,tour,level,band in product(['clay','hard'],['ATP','WTA'],['250','500','1000'],
                                     ['<1.30','1.30-1.40','1.40-1.50','1.50-1.70']):
    seg = [m for m in rows if m['surf']==surf and m['tour']==tour and str(m['level'])==level and odds_band(m['fav_odds'])==band]
    if len(seg)<100: continue
    s = calc_stats(seg, lambda m:(m['fav_won'],m['fav_odds'],m['yr']))
    if not s: continue
    yrs = yr_breakdown(seg, lambda m:(m['fav_won'],m['fav_odds'],m['yr']))
    pos_y = sum(1 for yr in ['2021','2022','2023','2024'] if yrs[yr] and yrs[yr]['roi']>0)
    F1.append({'label':f'Fav {band} {surf} {tour} L{level}','overall':s,'yrs':yrs,'pos_y':pos_y})
F1.sort(key=lambda x:x['overall']['roi'], reverse=True)
print(f"\n{'Top 20 Favorite Win Strategies:':.40}")
print(f"{'Label':<40} {'ROI':>8} {'n':>6} {'W%':>7} {'ML':>5} {'Yearly ROI':>50}")
for c in F1[:20]:
    o=c['overall']; y=c['yrs']
    yr_parts = []
    for yr in ['2021','2022','2023','2024']:
        if y[yr]: yr_parts.append(f"{yr}:{y[yr]['roi']:+.1f}%({y[yr]['n']})")
        else: yr_parts.append(f"{yr}:---")
    print(f"  {c['label']:<38} {o['roi']:+.2f}% {o['n']:>5} {o['win_pct']:>6}% {o['max_lose']:>4}  {' '.join(yr_parts)}")

# ================================================================
# 2a) TOTAL GAMES OVER
print("\n" + "="*90)
print("2) TOTAL GAMES OVER — surface x tour x line")
print("="*90)
TG_OVER = []
for surf,tour in product(['clay','hard'],['ATP','WTA']):
    for line in [19.5,20.5,21.5,22.5,23.5]:
        seg = [m for m in rows if m['surf']==surf and m['tour']==tour
               and m.get('total_line') and m.get('odds_total_over') and abs(m['total_line']-line)<0.01]
        if len(seg)<50: continue
        s = calc_stats(seg, lambda m:(m['tg']>line, m['odds_total_over'] if m['odds_total_over'] else 0, m['yr']))
        if not s: continue
        yrs = yr_breakdown(seg, lambda m:(m['tg']>line, m['odds_total_over'] if m['odds_total_over'] else 0, m['yr']))
        pos_y = sum(1 for yr in ['2021','2022','2023','2024'] if yrs[yr] and yrs[yr]['roi']>0)
        TG_OVER.append({'label':f'Over {line} {surf} {tour}','overall':s,'yrs':yrs,'pos_y':pos_y})
TG_OVER.sort(key=lambda x:x['overall']['roi'], reverse=True)
for c in TG_OVER[:25]:
    o=c['overall']; y=c['yrs']
    yr_parts = []
    for yr in ['2021','2022','2023','2024']:
        if y[yr]: yr_parts.append(f"{yr}:{y[yr]['roi']:+.1f}%({y[yr]['n']})")
        else: yr_parts.append(f"{yr}:---")
    print(f"  {c['label']:<25} ROI={o['roi']:+.2f}% n={o['n']:>4} P%={o['win_pct']:>5}% ML={o['max_lose']:>3}  {' '.join(yr_parts)}")

# ================================================================
# 2b) TOTAL GAMES UNDER
print("\n" + "="*90)
print("2b) TOTAL GAMES UNDER — surface x tour x line")
print("="*90)
TG_UNDER = []
for surf,tour in product(['clay','hard'],['ATP','WTA']):
    for line in [18.5,19.5,20.5,21.5]:
        seg = [m for m in rows if m['surf']==surf and m['tour']==tour
               and m.get('total_line') and m.get('odds_total_under') and abs(m['total_line']-line)<0.01]
        if len(seg)<50: continue
        s = calc_stats(seg, lambda m:(m['tg']<line, m['odds_total_under'] if m['odds_total_under'] else 0, m['yr']))
        if not s: continue
        yrs = yr_breakdown(seg, lambda m:(m['tg']<line, m['odds_total_under'] if m['odds_total_under'] else 0, m['yr']))
        pos_y = sum(1 for yr in ['2021','2022','2023','2024'] if yrs[yr] and yrs[yr]['roi']>0)
        TG_UNDER.append({'label':f'Under {line} {surf} {tour}','overall':s,'yrs':yrs,'pos_y':pos_y})
TG_UNDER.sort(key=lambda x:x['overall']['roi'], reverse=True)
for c in TG_UNDER[:25]:
    o=c['overall']; y=c['yrs']
    yr_parts = []
    for yr in ['2021','2022','2023','2024']:
        if y[yr]: yr_parts.append(f"{yr}:{y[yr]['roi']:+.1f}%({y[yr]['n']})")
        else: yr_parts.append(f"{yr}:---")
    print(f"  {c['label']:<25} ROI={o['roi']:+.2f}% n={o['n']:>4} P%={o['win_pct']:>5}% ML={o['max_lose']:>3}  {' '.join(yr_parts)}")

# ================================================================
# 3) TOTAL GAMES by upset vs non-upset
print("\n" + "="*90)
print("3) Total Games — Upset vs Non-Upset context")
print("="*90)

def is_upset(m):
    """p1 always wins. If p1 is unfavored (odds_p1 > odds_p2), it's an upset."""
    return m['odds_p1'] > m['odds_p2']

for uv_name, uv_val in [('NoUpset',0), ('Upset',1)]:
    for surf,tour in product(['clay','hard'],['ATP','WTA']):
        for line in [20.5, 21.5]:
            seg = [m for m in rows if is_upset(m)==uv_val and m['surf']==surf
                   and m['tour']==tour and m.get('total_line') and m.get('odds_total_over')
                   and abs(m['total_line']-line)<0.01]
            if len(seg)<30: continue
            s = calc_stats(seg, lambda m:(m['tg']>line, m['odds_total_over'] if m['odds_total_over'] else 0, m['yr']))
            if s and s['roi']>-30:
                print(f"  {uv_name:8s} | {surf} {tour} | Over {line}: n={s['n']}, O%={s['win_pct']}, ROI={s['roi']:+.2f}%")

# ================================================================
# 4) Sets Handicap — % 2:0 wins
print("\n" + "="*90)
print("4) Sets Handicap — % 2:0 wins among favorite wins")
print("="*90)
for band in ['<1.30','1.30-1.40','1.40-1.50','1.50-1.70']:
    for surf,tour in product(['clay','hard'],['ATP','WTA']):
        fw = [m for m in rows if m['fav_won'] and m['surf']==surf and m['tour']==tour
              and odds_band(m['fav_odds'])==band]
        if len(fw)<50: continue
        two_zero = sum(1 for m in fw if m['sets_loser']==0)
        pct = two_zero/len(fw)*100
        avg_o = sum(m['fav_odds'] for m in fw)/len(fw)
        handicap_avail = [m for m in fw if m.get('handicap_line')]
        print(f"  {band}|{surf}|{tour}: n={len(fw)}, 2:0={two_zero}({pct:.1f}%), avg_odds={avg_o:.2f}, handicaps={len(handicap_avail)}")

# ================================================================
# 5) Level (250/500/1000) analysis
print("\n" + "="*90)
print("5) Level analysis")
print("="*90)
for level in ['250','500','1000']:
    for surf in ['clay','hard']:
        seg = [m for m in rows if str(m['level'])==level and m['surf']==surf]
        if len(seg)<50: continue
        s = calc_stats(seg, lambda m:(m['fav_won'],m['fav_odds'],m['yr']))
        if not s: continue
        yrs = yr_breakdown(seg, lambda m:(m['fav_won'],m['fav_odds'],m['yr']))
        yr_parts = ' | '.join(f"{yr}:{y[yr]['roi']:+.1f}%({y[yr]['n']})" for yr in ['2021','2022','2023','2024'] if y.get(yr))
        print(f"  L{level} {surf}: ROI={s['roi']:+.2f}% n={s['n']} W%={s['win_pct']} | {yr_parts}")

# ================================================================
# 6) WTA vs ATP differences
print("\n" + "="*90)
print("6) WTA vs ATP — mid-range favorites")
print("="*90)
for tour in ['ATP','WTA']:
    for surf in ['clay','hard']:
        for band in ['1.40-1.50','1.50-1.70','1.70-2.00']:
            seg = [m for m in rows if m['tour']==tour and m['surf']==surf and odds_band(m['fav_odds'])==band]
            if len(seg)<50: continue
            s = calc_stats(seg, lambda m:(m['fav_won'],m['fav_odds'],m['yr']))
            if not s: continue
            yrs = yr_breakdown(seg, lambda m:(m['fav_won'],m['fav_odds'],m['yr']))
            yr_parts = ' | '.join(f"{yr}:{y[yr]['roi']:+.1f}%({y[yr]['n']})" for yr in ['2021','2022','2023','2024'] if y.get(yr))
            print(f"  {tour} {surf} {band}: ROI={s['roi']:+.2f}% n={s['n']} | {yr_parts}")

# ================================================================
# 7) Tiebreak analysis
print("\n" + "="*90)
print("7) Tiebreak correlation with total games over")
print("="*90)
for tb in [0,1]:
    seg = [m for m in rows if m.get('tiebreak')==tb and m.get('total_line') and m.get('odds_total_over')]
    if len(seg)<50: continue
    for line in [20.5,21.5,22.5]:
        sl = [m for m in seg if abs(m['total_line']-line)<0.01]
        if len(sl)<50: continue
        s = calc_stats(sl, lambda m:(m['tg']>line, m['odds_total_over'] if m['odds_total_over'] else 0, m['yr']))
        if s:
            print(f"  TB={tb} Over {line}: n={s['n']}, O%={s['win_pct']}, ROI={s['roi']:+.2f}%")

# ================================================================
# 8) Season timing
print("\n" + "="*90)
print("8) Season timing")
print("="*90)
def season(d):
    m = int(d[5:7])
    if m<=2: return 'Jan-Feb'
    if m<=3: return 'Mar'
    if m<=5: return 'Apr-May'
    if m<=6: return 'Jun'
    if m<=7: return 'Jul'
    if m<=8: return 'Aug'
    return 'Sep-Dec'

for sn in ['Jan-Feb','Mar','Apr-May','Jun','Jul','Aug','Sep-Dec']:
    seg = [m for m in rows if season(m['match_date'])==sn]
    if len(seg)<50: continue
    s = calc_stats(seg, lambda m:(m['fav_won'],m['fav_odds'],m['yr']))
    if s:
        yrs = yr_breakdown(seg, lambda m:(m['fav_won'],m['fav_odds'],m['yr']))
        yr_parts = ' | '.join(f"{yr}:{y[yr]['roi']:+.1f}%({y[yr]['n']})" for yr in ['2021','2022','2023','2024'] if y.get(yr))
        print(f"  {sn}: ROI={s['roi']:+.2f}% n={s['n']} W%={s['win_pct']} | {yr_parts}")

# ================================================================
# DEEP: Odds bin analysis
print("\n" + "="*90)
print("DEEP: Fine-grained odds bin analysis (0.10 bins)")
print("="*90)
for tour in ['ATP','WTA']:
    for surf in ['clay','hard']:
        bins = defaultdict(list)
        for m in rows:
            if m['tour']==tour and m['surf']==surf:
                bk = math.floor(m['fav_odds']*10)/10
                if 1.10 <= bk < 2.50:
                    bins[bk].append(m)
        for bk in sorted(bins.keys()):
            seg = bins[bk]
            if len(seg)<50: continue
            s = calc_stats(seg, lambda m:(m['fav_won'],m['fav_odds'],m['yr']))
            if s:
                yrs = yr_breakdown(seg, lambda m:(m['fav_won'],m['fav_odds'],m['yr']))
                yr_parts = ' | '.join(f"{yr}:{y[yr]['roi']:+.1f}%({y[yr]['n']})" for yr in ['2021','2022','2023','2024'] if y.get(yr))
                print(f"  {tour} {surf} {bk:.1f}: ROI={s['roi']:+.2f}% n={s['n']} W%={s['win_pct']} ML={s['max_lose']} | {yr_parts}")

# ================================================================
# COMBINED: All positive-ROI segments
print("\n" + "="*90)
print("ALL POSITIVE-ROI SEGMENTS (n>=100, overall ROI>0)")
print("="*90)
all_pos = []
for c in F1 + TG_OVER + TG_UNDER:
    o = c['overall']
    if o and o['n']>=100 and o['roi']>0:
        all_pos.append(c)
all_pos.sort(key=lambda x:x['overall']['roi'], reverse=True)
for c in all_pos[:30]:
    o=c['overall']; y=c['yrs']
    yr_parts = []
    for yr in ['2021','2022','2023','2024']:
        if y[yr]: yr_parts.append(f"{yr}:{y[yr]['roi']:+.1f}%({y[yr]['n']})")
        else: yr_parts.append(f"{yr}:---")
    print(f"  {c['label']:<30} ROI={o['roi']:+.2f}% n={o['n']:>5} pct={o['win_pct']:>5}% ML={o['max_lose']:>3}  {' '.join(yr_parts)}  pos={c['pos_y']}/4")

conn.close()
print("\n\nANALYSIS COMPLETE")
