import json,urllib.request,time,pickle,os,statistics as st,collections
def g(u):
    for k in range(3):
        try:
            r=urllib.request.Request('https://fantasy.premierleague.com/api/'+u,headers={'User-Agent':'Mozilla/5.0'})
            return json.load(urllib.request.urlopen(r,timeout=30))
        except Exception as ex:
            time.sleep(2)
    raise ex
C='elite.pkl'
if os.path.exists(C): X=pickle.load(open(C,'rb'))
else:
    X={'th':{},'m':{}}
    for name,page in (('top50',1),('1k',20),('10k',200),('100k',2000),('500k',10000),('1M',20000)):
        s=g(f'leagues-classic/314/standings/?page_standings={page}')['standings']['results']
        X['th'][name]=[(r['rank'],r['total'],r['entry']) for r in s]
        time.sleep(0.4)
    ids=[e for n in ('1k','10k') for (_,_,e) in X['th'][n][:30]]
    for e in ids:
        X['m'][e]={'h':g(f'entry/{e}/history/'),'p':{gw:g(f'entry/{e}/event/{gw}/picks/') for gw in (8,9,10)}}
        time.sleep(0.25)
    pickle.dump(X,open(C,'wb'))
D=pickle.load(open('cache.pkl','rb'));b=D['b'];E={p['id']:p for p in b['elements']}
for n,v in X['th'].items(): print(n,'rank',v[0][0],'total',v[0][1])
print('you: 585 (rank 3.6M)')
M=X['m']
def col(f): return [f(m) for m in M.values()]
print('\nElite sample n=%d (ranks ~1k and ~10k), season to GW10:'%len(M))
print(' total pts median',st.median(col(lambda m:m['h']['current'][-1]['total_points'])))
print(' bench pts total median',st.median(col(lambda m:sum(x['points_on_bench'] for x in m['h']['current']))),'(you 139)')
print(' hits total median',st.median(col(lambda m:sum(x['event_transfers_cost'] for x in m['h']['current']))),'(you 4)')
print(' transfers made median',st.median(col(lambda m:sum(x['event_transfers'] for x in m['h']['current']))),'(you 9)')
print(' team value median',st.median(col(lambda m:m['h']['current'][-1]['value']/10)),'(you 100.2)')
ch=collections.Counter(); 
for m in M.values():
    for c in m['h']['chips']: ch[(c['name'],)]+=1
print(' chips used (count of managers):',dict(ch))
chg=collections.Counter((c['name'],c['event']) for m in M.values() for c in m['h']['chips'])
print(' chip by GW:',sorted(chg.items(),key=lambda x:(x[0][0],x[0][1])))
print(' managers with 0 chips used:',sum(1 for m in M.values() if not m['h']['chips']))
# GW10 structure
own=collections.Counter();cap=collections.Counter();benchv=[];xi_v=[]
for m in M.values():
    pk=m['p'][10]['picks']
    for p in pk:
        own[p['element']]+=1
        if p['is_captain']: cap[p['element']]+=1
    benchv.append(sum(E[p['element']]['now_cost'] for p in pk if p['position']>11)/10)
print(' GW10 bench value median £%.1f'%st.median(benchv))
my=D['picks'][10]['picks']; print(' your GW10 bench value £%.1f'%(sum(E[p['element']]['now_cost'] for p in my if p['position']>11)/10))
print(' GW10 ownership in elite sample (top 22):')
mine=set(p['element'] for p in my)
for i,c in own.most_common(22): print(f"   {E[i]['web_name']:<16} £{E[i]['now_cost']/10:<5} {100*c/len(M):>4.0f}%  {'YOU' if i in mine else ''}")
print(' GW10 captains:',[(E[i]['web_name'],c) for i,c in cap.most_common(6)])
for gw in (8,9):
    cc=collections.Counter(next(p['element'] for p in m['p'][gw]['picks'] if p['is_captain']) for m in M.values())
    print(f' GW{gw} captains:',[(E[i]['web_name'],c) for i,c in cc.most_common(5)])
# captain points for elite across 8-10
pts={e:{x['id']:x['stats']['total_points'] for x in D['live'][e]['elements']} for e in D['live']}
print(' elite mean captain base pts GW8-10:',round(st.mean(pts[gw][next(p['element'] for p in m['p'][gw]['picks'] if p['is_captain'])] for m in M.values() for gw in (8,9,10)),2),'| yours GW8-10: 17,9,8')
print(' elite per-GW points median by GW:',[int(st.median(m['h']['current'][k]['points'] for m in M.values())) for k in range(10)])
