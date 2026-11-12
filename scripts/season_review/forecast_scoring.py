import json,glob,os,pickle,math
from datetime import datetime,timezone
R='/home/lewis/Workspace/fpl-agent/'
D=pickle.load(open('cache.pkl','rb'))
b=D['b'];E={p['id']:p for p in b['elements']};T={t['id']:t['short_name'] for t in b['teams']}
pts={e:{x['id']:x['stats']['total_points'] for x in D['live'][e]['elements']} for e in D['live']}
mins={e:{x['id']:x['stats']['minutes'] for x in D['live'][e]['elements']} for e in D['live']}
snaps=sorted(os.listdir(R+'data/raw/fpl/2026-27/snapshots/live'))
def snap_before(ts):
    key=ts.strftime('%Y%m%dT%H%M%S')
    c=[s for s in snaps if s[:15]<=key]
    return c[-1]
def spearman(a,b):
    def rk(v):
        o=sorted(range(len(v)),key=lambda i:v[i]);r=[0]*len(v)
        i=0
        while i<len(o):
            j=i
            while j+1<len(o) and v[o[j+1]]==v[o[i]]: j+=1
            for k in range(i,j+1): r[o[k]]=(i+j)/2
            i=j+1
        return r
    ra,rb=rk(a),rk(b);n=len(a);ma=sum(ra)/n;mb=sum(rb)/n
    num=sum((x-ma)*(y-mb) for x,y in zip(ra,rb));da=math.sqrt(sum((x-ma)**2 for x in ra));db=math.sqrt(sum((y-mb)**2 for y in rb))
    return num/(da*db)
rows=[]
print('GW  n   MAE_us MAE_fpl  bias_us bias_fpl  rho_us rho_fpl | top20 actual: us  fpl  oracle | top5 MID/FWD actual: us fpl')
for e in range(4,11):
    fs=sorted(glob.glob(R+f'data/decisions/weekly/event-{e}/*.json'),key=os.path.getmtime)
    d=json.load(open(fs[-1])); ef=d['event_player_forecasts']
    ts=datetime.fromisoformat(d['created_at'])
    s=snap_before(ts); bs=json.load(open(R+f'data/raw/fpl/2026-27/snapshots/live/{s}/bootstrap-static.json'))
    ep={p['id']:float(p['ep_next'] or 0) for p in bs['elements']}
    cost={p['id']:p['now_cost'] for p in bs['elements']}
    pool=[int(k) for k,v in ef.items() if (v['expected_points']>=2.0 or ep.get(int(k),0)>=2.0) and int(k) in pts[e]]
    us=[ef[str(i)]['expected_points'] for i in pool]; fp=[ep.get(i,0) for i in pool]; ac=[pts[e][i] for i in pool]
    n=len(pool)
    mae=lambda p:sum(abs(x-y) for x,y in zip(p,ac))/n; bias=lambda p:sum(x-y for x,y in zip(p,ac))/n
    top=lambda p,k,ids=pool:sum(pts[e][i] for i in sorted(ids,key=lambda i:-p[i])[:k])/k
    usd={i:ef[str(i)]['expected_points'] for i in pool}; fpd={i:ep.get(i,0) for i in pool}; acd={i:pts[e][i] for i in pool}
    att=[i for i in pool if E[i]['element_type'] in (3,4)]
    print(f"{e:>2} {n:>4} {mae(us):>6.2f} {mae(fp):>6.2f} {bias(us):>+7.2f} {bias(fp):>+7.2f} {spearman(us,ac):>7.3f} {spearman(fp,ac):>6.3f} | {top(usd,20):>14.2f} {top(fpd,20):>5.2f} {top(acd,20):>6.2f} | {top(usd,5,att):>10.2f} {top(fpd,5,att):>5.2f}")
    for i in pool: rows.append((e,i,ef[str(i)]['expected_points'],ep.get(i,0),pts[e][i],mins[e][i],ef[str(i)].get('expected_minutes'),cost.get(i,0),E[i]['element_type']))
pickle.dump(rows,open('fc_rows.pkl','wb'))
n=len(rows)
print('ALL n',n,'MAE us %.3f fpl %.3f | bias us %+.3f fpl %+.3f | rho us %.3f fpl %.3f'%(sum(abs(r[2]-r[4]) for r in rows)/n,sum(abs(r[3]-r[4]) for r in rows)/n,sum(r[2]-r[4] for r in rows)/n,sum(r[3]-r[4] for r in rows)/n,spearman([r[2] for r in rows],[r[4] for r in rows]),spearman([r[3] for r in rows],[r[4] for r in rows])))
print('\nBy position: n, mean forecast us, fpl, actual')
for k,nm in ((1,'GK'),(2,'DEF'),(3,'MID'),(4,'FWD')):
    rr=[r for r in rows if r[8]==k]; m=len(rr)
    print(f"  {nm} {m:>4}  us {sum(r[2] for r in rr)/m:.2f}  fpl {sum(r[3] for r in rr)/m:.2f}  actual {sum(r[4] for r in rr)/m:.2f}  rho us {spearman([r[2] for r in rr],[r[4] for r in rr]):.3f} fpl {spearman([r[3] for r in rr],[r[4] for r in rr]):.3f}")
print('\nBy price band: n, us, fpl, actual')
for lo,hi in ((0,50),(50,65),(65,85),(85,110),(110,200)):
    rr=[r for r in rows if lo<=r[7]<hi]; m=len(rr)
    if m: print(f"  £{lo/10}-{hi/10}: {m:>4}  us {sum(r[2] for r in rr)/m:.2f}  fpl {sum(r[3] for r in rr)/m:.2f}  actual {sum(r[4] for r in rr)/m:.2f}")
print('\nCalibration by our forecast bucket: n, mean us, actual | fpl bucket: n, mean fpl, actual')
for lo,hi in ((2,3),(3,4),(4,5),(5,6),(6,20)):
    a=[r for r in rows if lo<=r[2]<hi]; c=[r for r in rows if lo<=r[3]<hi]
    print(f"  {lo}-{hi}: us n {len(a):>4} fc {sum(r[2] for r in a)/max(len(a),1):.2f} act {sum(r[4] for r in a)/max(len(a),1):.2f} | fpl n {len(c):>4} fc {sum(r[3] for r in c)/max(len(c),1):.2f} act {sum(r[4] for r in c)/max(len(c),1):.2f}")
print('\nMinutes: forecast vs actual for our forecast>=3 players')
rr=[r for r in rows if r[2]>=3 and r[6] is not None]
print('  n',len(rr),'mean exp min %.1f actual %.1f | DNP rate %.1f%% | <45min rate %.1f%%'%(sum(r[6] for r in rr)/len(rr),sum(r[5] for r in rr)/len(rr),100*sum(r[5]==0 for r in rr)/len(rr),100*sum(r[5]<45 for r in rr)/len(rr)))
print('\nHaaland per GW: ours, fpl ep, actual')
h=next(p['id'] for p in b['elements'] if p['web_name']=='Haaland')
for r in rows:
    if r[1]==h: print('  GW',r[0],'us %.2f fpl %.2f actual %d'%(r[2],r[3],r[4]))
print('Haaland all GWs actual:',[pts[e].get(h,0) for e in range(1,11)])
print('\nOur top-5 ranked players each GW (any position) with actual:')
for e in range(4,11):
    rr=sorted([r for r in rows if r[0]==e],key=lambda r:-r[2])[:5]
    print('  GW',e,', '.join(f"{E[r[1]]['web_name']} {r[2]:.1f}->{r[4]}" for r in rr))
print('FPL ep_next top-5 each GW:')
for e in range(4,11):
    rr=sorted([r for r in rows if r[0]==e],key=lambda r:-r[3])[:5]
    print('  GW',e,', '.join(f"{E[r[1]]['web_name']} {r[3]:.1f}->{r[4]}" for r in rr))
