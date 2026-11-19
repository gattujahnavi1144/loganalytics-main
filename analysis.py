"""Simple starter: run python analysis.py (standard library only)."""
import csv
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
P=Path(__file__).resolve().parent
with (P/'requests.csv').open(newline='',encoding='utf-8') as f:
    rows=list(csv.DictReader(f))
for r in rows:
    r['status']=int(r['status'])
    r['latency_ms']=int(r['latency_ms'])
    r['dt']=datetime.fromisoformat(r['timestamp'].replace('Z','+00:00'))

def percentile(a,p):
    a=sorted(a)
    if not a:return None
    return a[round((len(a)-1)*p)]

print('Requests:',len(rows))
print('Status distribution:',dict(Counter(r['status'] for r in rows)))
print('5xx error rate:',round(100*sum(r['status']>=500 for r in rows)/len(rows),2),'%')
print('Latency p50/p95/p99 (ms):',*[percentile([r['latency_ms'] for r in rows],p) for p in [.5,.95,.99]])
print('\nERRORS BY REGION / CODE')
c=Counter((r['region'],r['error_code']) for r in rows if r['error_code'])
for (region,code),n in c.most_common():print(f'{region:12} {code:28} {n:5}')
print('\nFIVE-MINUTE WINDOW: request counts, 5xx count, 5xx rate')
groups=defaultdict(list)
for r in rows:
    t=r['dt'];minute=(t.minute//5)*5
    key=t.replace(minute=minute,second=0,microsecond=0)
    groups[key].append(r)
for t,g in sorted(groups.items()):
    fails=sum(x['status']>=500 for x in g)
    print(t.strftime('%H:%M'),len(g),fails,f'{fails/len(g)*100:.1f}%')
print('\nINVESTIGATE NEXT:')
print('1. Filter /api/v1/checkout failures; join by trace_id to application_logs.jsonl')
print('2. Correlate five-minute error rate with metrics.csv')
print('3. Investigate v2.8.0 by region / endpoint / time window')
