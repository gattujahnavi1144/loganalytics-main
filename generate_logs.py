#!/usr/bin/env python3
"""Deterministic, fictional ShopSphere distributed-system log generator."""
import csv, json, random, uuid, zipfile, collections
from datetime import datetime, timedelta, timezone
from pathlib import Path
R=random.Random(20261119)
OUT=Path(__file__).resolve().parent
START=datetime(2026,11,18,9,0,tzinfo=timezone.utc)
N=12000
services=['api-gateway','auth-service','catalog-service','cart-service','inventory-service','order-service','payment-service','notification-worker']
hosts={s:[f'{s[:8]}-{i:02d}' for i in range(1,4)] for s in services}
ids=collections.Counter()
logs=[]; reqs=[]; metrics=[]
def between(t,a,b): return a<=t<b
def mins(t):return (t-START).total_seconds()/60

def emit(t,trace,span,parent,service,level,event,msg,latency,status,user,tenant,region,endpoint,method,error='',deploy='v2.7.3',extra=None):
    ids[service]+=1
    logs.append(dict(timestamp=t.isoformat(timespec='milliseconds').replace('+00:00','Z'),level=level,service=service,environment='production',region=region,host=R.choice(hosts[service]),deployment_version=deploy,trace_id=trace,span_id=span,parent_span_id=parent,request_id=trace[:16],tenant_id=tenant,user_id=user,method=method,endpoint=endpoint,event=event,message=msg,http_status=status,latency_ms=latency,error_code=error,details=json.dumps(extra or {},sort_keys=True,separators=(',',':'))))

routes=[('/api/v1/products','GET',.29),('/api/v1/login','POST',.17),('/api/v1/cart','POST',.14),('/api/v1/checkout','POST',.26),('/api/v1/orders','GET',.14)]
def choose_route():
    k=R.random();total=0
    for p,m,w in routes:
        total+=w
        if k<=total:return p,m
    return routes[-1][:2]

for i in range(N):
    t=START+timedelta(seconds=(i*1.2)+R.uniform(-.5,.5)) # 4 hours
    minute=mins(t)
    endpoint,method=choose_route()
    region=R.choices(['us-east-1','eu-west-1','ap-south-1'],[.65,.20,.15])[0]
    tenant=R.choice(['acme','globex','initech','umbrella','waystar'])
    user=f'user-{R.randint(1,2600):04d}'
    trace=uuid.UUID(int=R.getrandbits(128)).hex
    gateway=uuid.UUID(int=R.getrandbits(64)).hex[:16]
    version='v2.8.0' if minute>=165 and region=='us-east-1' else 'v2.7.3'
    chain={'/api/v1/products':['catalog-service'],'/api/v1/login':['auth-service'],'/api/v1/cart':['auth-service','cart-service','inventory-service'],'/api/v1/checkout':['auth-service','cart-service','inventory-service','order-service','payment-service','notification-worker'],'/api/v1/orders':['auth-service','order-service']}[endpoint]
    attack=between(minute,55,90) and endpoint=='/api/v1/login' and R.random()<.72
    payment_incident=between(minute,105,155) and endpoint=='/api/v1/checkout' and region=='us-east-1' and R.random()<.70
    inventory_incident=between(minute,125,170) and 'inventory-service' in chain and R.random()<.42
    db_incident=between(minute,145,185) and ('order-service' in chain) and R.random()<.55
    deployment_incident=between(minute,165,220) and version=='v2.8.0' and R.random()<.38
    overall=200; end_code=''; spans=[]; total=R.randint(12,45)
    ip=f'198.51.100.{R.randint(1,254)}' if attack else f'203.0.113.{R.randint(1,254)}'
    for j,service in enumerate(chain):
        span=uuid.UUID(int=R.getrandbits(64)).hex[:16]
        parent=gateway if j==0 else spans[-1]
        spans.append(span)
        lat=max(3,int(R.lognormvariate(3.0,.48)))
        code=200;error='';event='request.completed';level='INFO';msg=f'{service} processed request'
        details={'attempt':1,'ip':ip}
        if service=='auth-service' and attack:
            code=401; error='AUTH_INVALID_CREDENTIALS'; lat+=R.randint(20,80);msg='Invalid credentials; authentication rejected';event='auth.login.failed';level='WARN';details.update({'source_ip':'198.51.100.77','attempt':R.randint(10,900),'user_agent':'python-requests/2.32'})
        elif service=='payment-service' and payment_incident:
            code=504;error='PAYMENT_PROVIDER_TIMEOUT';lat+=R.randint(2400,6200);msg='Upstream payment processor timeout';event='payment.gateway.timeout';level='ERROR';details.update({'provider':'PayBridge','upstream':'payments.partner.example','timeout_ms':2500,'retry_count':R.randint(2,4)})
        elif service=='inventory-service' and inventory_incident:
            code=409;error='INVENTORY_DEADLOCK';lat+=R.randint(750,2600);msg='Inventory reservation transaction deadlocked';event='inventory.tx.deadlock';level='ERROR';details.update({'db':'inventory-db','lock_wait_ms':lat,'sku':'SKU-'+str(R.randint(1000,1035))})
        elif service=='order-service' and db_incident:
            code=503;error='DB_POOL_EXHAUSTED';lat+=R.randint(1400,4100);msg='No available connection from order database pool';event='db.pool.exhausted';level='ERROR';details.update({'pool_max':30,'pool_active':30,'wait_ms':lat})
        elif service in ['auth-service','order-service','payment-service'] and deployment_incident:
            code=500;error='NULL_CUSTOMER_CONTEXT';lat+=R.randint(300,1400);msg='Unhandled exception: customer context null';event='application.exception';level='ERROR';details.update({'stack':'CheckoutContextResolver.resolve:118','feature_flag':'new-checkout-context'})
        elif R.random()<.007:
            code=500;error='TRANSIENT_FAILURE';lat+=R.randint(160,650);msg='Transient service processing failure';event='application.error';level='ERROR'
        emit(t+timedelta(milliseconds=total),trace,span,parent,service,level,event,msg,lat,code,user,tenant,region,endpoint,method,error,version,details)
        total+=lat
        if code>=400 and overall==200:
            overall=code;end_code=error
            # fail fast; notification-worker should not execute after checkout failure
            break
    if endpoint=='/api/v1/checkout' and overall==200 and between(minute,105,175) and R.random()<.18:
        # Successful checkout but message queue delayed (post-commit async issue)
        emit(t+timedelta(milliseconds=total+R.randint(5000,35000)),trace,uuid.UUID(int=R.getrandbits(64)).hex[:16],spans[-1],'notification-worker','WARN','queue.consumer.lag','Order email delayed due to queue backlog',R.randint(5000,35000),200,user,tenant,region,endpoint,method,'QUEUE_CONSUMER_LAG',version,{'queue':'order-events','lag_messages':R.randint(1200,6500),'consumer_group':'mailer-v2'})
    if endpoint=='/api/v1/login' and attack:
        # Extra auth audit line; an auth failure is often client-visible 401 rather than a server error
        emit(t+timedelta(milliseconds=total+2),trace,uuid.UUID(int=R.getrandbits(64)).hex[:16],gateway,'auth-service','WARN','security.brute_force_indicator','Repeated login failures from single source IP',0,401,user,tenant,region,endpoint,method,'SUSPICIOUS_LOGIN',version,{'ip':'198.51.100.77','risk_score':R.randint(80,99)})
    emit(t+timedelta(milliseconds=total+4),trace,gateway,'','api-gateway','ERROR' if overall>=500 else ('WARN' if overall>=400 else 'INFO'),'http.response','Completed incoming HTTP request',total,overall,user,tenant,region,endpoint,method,end_code,version,{'client_ip':'198.51.100.77' if attack else ip,'bytes_sent':R.randint(100,4800),'user_agent':'python-requests/2.32' if attack else 'ShopSphere-Web/6.1'})
    reqs.append(dict(timestamp=t.isoformat(timespec='milliseconds').replace('+00:00','Z'),request_id=trace[:16],trace_id=trace,region=region,tenant_id=tenant,user_id=user,method=method,endpoint=endpoint,status=overall,latency_ms=total,error_code=end_code,version=version))

# Background telemetry: CPU/heap and database pools (5-min intervals, per region)
for m in range(0,240,5):
  for region in ['us-east-1','eu-west-1','ap-south-1']:
    t=START+timedelta(minutes=m)
    deploy=(m>=165 and region=='us-east-1')
    base_heap=44+R.randint(-4,4)
    heap=min(96,base_heap+(m-165)*.85) if deploy else base_heap
    pool=30 if region=='us-east-1' and 145<=m<185 else R.randint(7,19)
    queue=R.randint(0,130)
    if 105<=m<175: queue=R.randint(1800,6500)
    metrics.append(dict(timestamp=t.isoformat().replace('+00:00','Z'),region=region,service='order-service',metric='db_pool_active',value=pool,unit='connections'))
    metrics.append(dict(timestamp=t.isoformat().replace('+00:00','Z'),region=region,service='api-gateway',metric='heap_used_pct',value=round(heap,1),unit='percent'))
    metrics.append(dict(timestamp=t.isoformat().replace('+00:00','Z'),region=region,service='notification-worker',metric='queue_lag_messages',value=queue,unit='messages'))
    metrics.append(dict(timestamp=t.isoformat().replace('+00:00','Z'),region=region,service='payment-service',metric='provider_p95_ms',value=R.randint(2700,6100) if region=='us-east-1' and 105<=m<155 else R.randint(90,280),unit='milliseconds'))

logs.sort(key=lambda x:x['timestamp'])
for name,rows in [('application_logs.jsonl',logs)]:
 with (OUT/name).open('w',encoding='utf-8') as f:
  for r in rows:f.write(json.dumps(r,separators=(',',':'))+'\n')
for name,rows in [('application_logs.csv',logs),('requests.csv',reqs),('metrics.csv',metrics)]:
 with (OUT/name).open('w',newline='',encoding='utf-8') as f:
  writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
print('event_logs',len(logs),'requests',len(reqs),'metrics',len(metrics))
print('status',collections.Counter(r['status'] for r in reqs))
print('errors',collections.Counter(r['error_code'] for r in reqs).most_common())
