import json,urllib.request,itertools,os,pickle
def g(u):
    return json.load(urllib.request.urlopen('https://fantasy.premierleague.com/api/'+u))
C='cache.pkl'
if os.path.exists(C): D=pickle.load(open(C,'rb'))
else:
    D={'b':g('bootstrap-static/'),'h':g('entry/2754976/history/'),'t':g('entry/2754976/transfers/')}
    D['picks']={e:g(f'entry/2754976/event/{e}/picks/') for e in range(1,11)}
    D['live']={e:g(f'event/{e}/live/') for e in range(1,11)}
    pickle.dump(D,open(C,'wb'))
b=D['b'];E={p['id']:p for p in b['elements']};T={t['id']:t['short_name'] for t in b['teams']}
pos={1:'GK',2:'DEF',3:'MID',4:'FWD'}
pts={e:{x['id']:x['stats']['total_points'] for x in D['live'][e]['elements']} for e in D['live']}
mins={e:{x['id']:x['stats']['minutes'] for x in D['live'][e]['elements']} for e in D['live']}
def best_xi(ids,e):
    # hindsight best legal XI + captain
    byp={k:sorted([i for i in ids if E[i]['element_type']==k],key=lambda i:-pts[e].get(i,0)) for k in (1,2,3,4)}
    best=0
    for d in (3,4,5):
        for m in (2,3,4,5):
            f=10-d-m
            if f<1 or f>3: continue
            xi=byp[1][:1]+byp[2][:d]+byp[3][:m]+byp[4][:f]
            s=sum(pts[e].get(i,0) for i in xi)+max(pts[e].get(i,0) for i in xi)
            best=max(best,s)
    return best
print('GW  got  capt(pts)            bestcap(pts)        capLoss benchPts hindsightXI  xiLoss(excl cap)')
tc=tb=tx=0
for e in range(1,11):
    pk=D['picks'][e]['picks']; ids=[p['element'] for p in pk]
    cap=next(p['element'] for p in pk if p['is_captain'])
    xi=[p['element'] for p in pk if p['multiplier']>0]
    eh=D['picks'][e]['entry_history']
    # effective captain (multiplier 2)
    eff=next((p['element'] for p in pk if p['multiplier']>=2),cap)
    bestc=max(xi,key=lambda i:pts[e].get(i,0))
    closs=pts[e].get(bestc,0)-pts[e].get(eff,0)
    hx=best_xi(ids,e)
    got=eh['points']
    print(f"{e:>2} {got:>4}  {E[cap]['web_name'][:14]:<14}({pts[e].get(eff,0):>2}) {E[bestc]['web_name'][:14]:<14}({pts[e].get(bestc,0):>2}) {closs:>6} {eh['points_on_bench']:>7} {hx:>10} {hx-got:>6}")
    tc+=closs;tb+=eh['points_on_bench'];tx+=hx-got
print('totals: captain loss vs best-in-XI',tc,'| bench pts',tb,'| hindsight XI+cap gap',tx)
print()
print('TRANSFERS (points from GW of transfer through GW10)')
net=0
for t in sorted(D['t'],key=lambda t:t['event']):
    e0=t['event']
    pin=sum(pts[e].get(t['element_in'],0) for e in range(e0,11)); pout=sum(pts[e].get(t['element_out'],0) for e in range(e0,11))
    # weeks held
    held=[e for e in range(e0,11) if t['element_in'] in [p['element'] for p in D['picks'][e]['picks']]]
    pin_h=sum(pts[e].get(t['element_in'],0) for e in held); pout_h=sum(pts[e].get(t['element_out'],0) for e in held)
    net+=pin_h-pout_h
    print(f"GW{e0:>2} {E[t['element_out']]['web_name']:<14} -> {E[t['element_in']]['web_name']:<14} while held ({len(held)}w): in {pin_h:>3} out {pout_h:>3} net {pin_h-pout_h:>+4} | to GW10: in {pin} out {pout}")
print('net while held',net,'hits',sum(x['event_transfers_cost'] for x in D['h']['current']))
print()
print('GW1 squad season points vs price')
ids1=[p['element'] for p in D['picks'][1]['picks']]
for i in sorted(ids1,key=lambda i:-E[i]['total_points']): print(f"  {E[i]['web_name']:<16}{pos[E[i]['element_type']]} {T[E[i]['team']]} start£{(E[i]['now_cost']-E[i]['cost_change_start'])/10} now£{E[i]['now_cost']/10} pts {E[i]['total_points']} own {E[i]['selected_by_percent']}%")
print()
print('TOP 25 scorers to date and whether owned in any GW')
owned={e:set(p['element'] for p in D['picks'][e]['picks']) for e in range(1,11)}
for p in sorted(b['elements'],key=lambda p:-p['total_points'])[:25]:
    w=[e for e in range(1,11) if p['id'] in owned[e]]
    print(f"  {p['web_name']:<16}{pos[p['element_type']]} {T[p['team']]} £{p['now_cost']/10:<5} pts {p['total_points']:>3} own {p['selected_by_percent']:>5}%  owned GWs: {w if w else '-'}")
