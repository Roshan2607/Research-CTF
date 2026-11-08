"""Persistent cumulative four-level event workflow."""
from __future__ import annotations
import hashlib,hmac,json,os,secrets,threading,csv
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parent
STATE=Path(os.environ.get("UL_EVENT_STATE") or ROOT/"data/submissions/event_state.json")
LOCK=threading.RLock()
CLUSTER="Hidden Structures: Networking × Evolutionary Biology"
CONTENT=ROOT/"data/event_content.csv"; TEAM_CSV=ROOT/"data/teams.csv"; SUB_CSV=ROOT/"data/submissions.csv"; LOG=ROOT/"data/realtime_events.jsonl"

def now(): return datetime.now(timezone.utc).isoformat(timespec="seconds")

def _read_csv(path):
    with path.open(encoding="utf-8-sig",newline="") as f:return list(csv.DictReader(f))

def _content(): return _read_csv(CONTENT)

def clusters():
    return sorted({r.get("cluster","").strip() for r in _content() if r.get("cluster","").strip()})

def levels_for_cluster(cluster=CLUSTER):
    rows=[r for r in _content() if r.get("cluster","").strip()==cluster]
    out=[]
    level_numbers=sorted({int(r["level"]) for r in rows if r.get("level","").isdigit()})
    for n in level_numbers:
        group=[r for r in rows if int(r['level'])==n]
        first=group[0] if group else {}
        out.append({'id':n,'title':first.get('level_title',f'Level {n}'),'question':first.get('flag_question',''),'hints':[x for x in first.get('hints','').split('|') if x], 'answers':[x.strip() for x in first.get('flag_answers','').split('|') if x.strip()], 'paper_ids':[r['paper_id'] for r in group]})
    return out

def create_cluster_from_template(name, template_cluster=CLUSTER):
    name=(name or "").strip()
    if not name: raise ValueError("Enter a cluster name.")
    rows=_content()
    if any(r.get("cluster","").strip().casefold()==name.casefold() for r in rows):
        raise ValueError("That cluster already exists in event_content.csv.")
    template=[r for r in rows if r.get("cluster","").strip()==template_cluster]
    if not template: raise ValueError("The selected template cluster has no papers.")
    copied=[]
    for row in template:
        item=dict(row);item["cluster"]=name;copied.append(item)
    fields=list(rows[0].keys()) if rows else list(copied[0].keys())
    with CONTENT.open("w",newline="",encoding="utf-8-sig") as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(rows+copied)
    log_event({"at":now(),"event":"cluster_created","cluster":name,"template_cluster":template_cluster})
    return name

LEVELS=levels_for_cluster(CLUSTER)
def _empty():return {'teams':{},'drafts':{},'attempts':{},'submissions':{},'audit':[],'session_tokens':{},'admin_tokens':{}}
def load():
    with LOCK:
        if not STATE.exists():return _empty()
        try:
            d=json.loads(STATE.read_text(encoding='utf-8')); d.setdefault('teams',{});d.setdefault('drafts',{});d.setdefault('attempts',{});d.setdefault('submissions',{});d.setdefault('audit',[]);d.setdefault('session_tokens',{});d.setdefault('admin_tokens',{});return d
        except (ValueError,OSError):return _empty()
def _sync_exports(d):
    ROOT.joinpath('data').mkdir(exist_ok=True)
    with TEAM_CSV.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=['cluster','team_id','team_name','password_salt','password_hash','created_at']);w.writeheader()
        for t in d['teams'].values():w.writerow({'cluster':t['cluster'],'team_id':t['team_id'],'team_name':t['name'],'password_salt':t['salt'],'password_hash':t['password_hash'],'created_at':t['created_at']})
    with SUB_CSV.open('w',newline='',encoding='utf-8') as f:
        fields=['team_id','team_name','cluster','level','submitted_at','submitted_flag','flag_correct','locked','edge_count','graph_csv']
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for rec in d['submissions'].values():
            t=d['teams'].get(rec['team_id'],{});w.writerow({'team_id':rec['team_id'],'team_name':t.get('name',''),'cluster':t.get('cluster',CLUSTER),'level':rec['level'],'submitted_at':rec['submitted_at'],'submitted_flag':rec.get('submitted_flag',''),'flag_correct':rec.get('flag_correct',False),'locked':True,'edge_count':rec.get('edge_count',0),'graph_csv':rec.get('csv','')})
def log_event(event):
    LOG.parent.mkdir(parents=True,exist_ok=True)
    with LOG.open('a',encoding='utf-8') as f:f.write(json.dumps(event,ensure_ascii=False)+'\n')
def save(d):
    with LOCK:
        STATE.parent.mkdir(parents=True,exist_ok=True);tmp=STATE.with_suffix('.tmp');tmp.write_text(json.dumps(d,indent=2,ensure_ascii=False),encoding='utf-8');tmp.replace(STATE);_sync_exports(d)
def _hash(password,salt=None):
    salt=salt or secrets.token_hex(16);return salt,hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),180000).hex()
def re_team_id(v):
    import re;return bool(re.fullmatch(r'[A-Z0-9_-]{3,20}',v))
def create_team(team_id,name,password,cluster=CLUSTER):
    team_id=team_id.strip().upper()
    if not re_team_id(team_id) or not name.strip() or len(password)<8:raise ValueError('Use a team ID like TEAM01, a team name, and a password of at least 8 characters.')
    if cluster not in clusters():raise ValueError('Choose a cluster listed in data/event_content.csv.')
    d=load()
    if team_id in d['teams']:raise ValueError('That team ID already exists.')
    salt,digest=_hash(password);d['teams'][team_id]={'team_id':team_id,'name':name.strip(),'cluster':cluster,'salt':salt,'password_hash':digest,'created_at':now()};d['audit'].append({'at':now(),'action':'team_created','team_id':team_id});save(d);log_event({'at':now(),'event':'team_created','team_id':team_id});return team_id
def authenticate(team_id,password):
    t=load()['teams'].get((team_id or '').strip().upper())
    if not t:return None
    _,candidate=_hash(password,t['salt'])
    return {'team_id':t['team_id'],'name':t['name'],'cluster':t['cluster']} if hmac.compare_digest(candidate,t['password_hash']) else None

def create_session(team_id):
    d=load(); token=secrets.token_urlsafe(32); digest=hashlib.sha256(token.encode()).hexdigest();d.setdefault('session_tokens',{})[digest]={'team_id':team_id,'created_at':now()};save(d);log_event({'at':now(),'event':'participant_login','team_id':team_id});return token

def authenticate_session(token):
    if not token:return None
    d=load();entry=d.get('session_tokens',{}).get(hashlib.sha256(token.encode()).hexdigest())
    if not entry:return None
    t=d['teams'].get(entry['team_id'])
    return {'team_id':t['team_id'],'name':t['name'],'cluster':t['cluster']} if t else None

def revoke_session(token):
    if not token:return
    d=load();d.get('session_tokens',{}).pop(hashlib.sha256(token.encode()).hexdigest(),None);save(d)


def create_admin_session():
    d=load();token=secrets.token_urlsafe(32);d.setdefault('admin_tokens',{})[hashlib.sha256(token.encode()).hexdigest()]={'created_at':now()};save(d);log_event({'at':now(),'event':'admin_login'});return token

def authenticate_admin_session(token):
    return bool(token and hashlib.sha256(token.encode()).hexdigest() in load().get('admin_tokens',{}))

def revoke_admin_session(token):
    if not token:return
    d=load();d.get('admin_tokens',{}).pop(hashlib.sha256(token.encode()).hexdigest(),None);save(d)

def released_papers(level, cluster=CLUSTER):
    return [p for l in levels_for_cluster(cluster) if l['id']<=level for p in l['paper_ids']]
def get_draft(team,level):
    d=load();key=f'{team}:{level}'
    if key in d['drafts']:return d['drafts'][key]
    prev=d['submissions'].get(f'{team}:{level-1}') if level>1 else None
    return prev['csv'] if prev else ''
def save_draft(team,level,csv_text):
    d=load();key=f'{team}:{level}'
    if key in d['submissions']:raise PermissionError('This level is locked.')
    d['drafts'][key]=csv_text;save(d);log_event({'at':now(),'event':'draft_saved','team_id':team,'level':level})
def normalise(s):
    import re,unicodedata
    s=unicodedata.normalize('NFKD',str(s or '')).encode('ascii','ignore').decode().lower();return re.sub(r'[^a-z0-9]+',' ',s).strip()
def attempt_flag(team,level,answer):
    d=load();key=f'{team}:{level}'
    if key in d['submissions']:return {'correct':False,'message':'This level is already locked.'}
    team_rec=d['teams'].get(team)
    if not team_rec:return {'correct':False,'message':'Team not found.'}
    specs=levels_for_cluster(team_rec.get('cluster',CLUSTER))
    spec=next((x for x in specs if x['id']==level),None)
    if spec is None:return {'correct':False,'message':'This level is not configured for your cluster.'}
    if not str(answer or '').strip():return {'correct':False,'message':'Enter a flag answer before submitting an attempt.'}
    correct=normalise(answer) in {normalise(x) for x in spec['answers']}
    attempt={'at':now(),'answer':str(answer).strip(),'correct':correct};d['attempts'].setdefault(key,[]).append(attempt);save(d);log_event({'at':attempt['at'],'event':'flag_attempt','team_id':team,'level':level,'correct':correct,'answer':attempt['answer']})
    return {'correct':correct,'message':'Correct flag.' if correct else 'Incorrect flag. You can still submit your graph and continue.'}
def flag_status(team,level):
    a=load()['attempts'].get(f'{team}:{level}',[]);return {'correct':any(x['correct'] for x in a),'attempts':len(a),'history':a,'last':a[-1] if a else None}
def finalise(team,level,csv_text,flag_correct,graph_score,submitted_flag=''):
    d=load();key=f'{team}:{level}'
    if key in d['submissions']:raise PermissionError('This level has already been submitted and locked.')
    attempts=d['attempts'].get(key,[])
    if not attempts:raise ValueError('Submit at least one flag attempt before advancing to the next level.')
    flag_correct=any(x['correct'] for x in attempts)
    import pandas as pd,io
    try: edge_count=len(pd.read_csv(io.StringIO(csv_text)))
    except Exception:edge_count=0
    rec={'team_id':team,'level':level,'submitted_at':now(),'csv':csv_text,'graph_score':graph_score,'flag_correct':flag_correct,'submitted_flag':submitted_flag,'locked':True,'edge_count':edge_count}
    d['submissions'][key]=rec;d['audit'].append({'at':rec['submitted_at'],'action':'level_submitted','team_id':team,'level':level,'flag_correct':flag_correct});save(d);log_event({'at':rec['submitted_at'],'event':'level_submitted','team_id':team,'level':level,'flag_correct':flag_correct,'edge_count':edge_count});return rec
def team_progress(team):
    d=load()
    team_rec=d['teams'].get(team,{})
    configured=levels_for_cluster(team_rec.get('cluster',CLUSTER))
    level_ids=[x['id'] for x in configured]
    completed=[i for i in level_ids if f'{team}:{i}' in d['submissions']]
    return completed,next((i for i in level_ids if i not in completed),None)
def admin_snapshot():
    d=load();teams=[]
    for tid,t in d['teams'].items():
        completed,_=team_progress(tid);teams.append({k:t[k] for k in ('team_id','name','cluster','created_at')}|{'completed_levels':completed})
    return {'teams':teams,'drafts':d['drafts'],'attempts':d['attempts'],'submissions':d['submissions'],'audit':d['audit']}
