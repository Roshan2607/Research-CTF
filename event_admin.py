"""Local-only admin dashboard with periodic live refresh."""
from pathlib import Path
import os,io,html
import pandas as pd
import streamlit as st
import extra_streamlit_components as stx
from datetime import datetime,timedelta
from dotenv import load_dotenv
load_dotenv(Path(__file__).with_name('.env'))
from event_core import LEVELS,CLUSTER,clusters,create_cluster_from_template,create_team,admin_snapshot,load,create_admin_session,authenticate_admin_session,revoke_admin_session
from challenge.participant_data import load_corpus

st.set_page_config(page_title='Uncharted Literature · Admin',page_icon='🔐',layout='wide')
st.title('🔐 Uncharted Literature · Admin');st.caption('Live organiser dashboard')

cookie_manager=stx.CookieManager(key='ul_admin_cookie')
cookies=cookie_manager.get_all()
if cookies is None:
    st.info('Restoring admin session…')
    st.stop()
admin_token=(cookies.get('ul_admin_session') if isinstance(cookies,dict) else None) or cookie_manager.get('ul_admin_session')
if not st.session_state.get('event_admin') and authenticate_admin_session(admin_token):
    st.session_state['event_admin']=True

if not st.session_state.get('event_admin'):
    with st.form('admin_login'):
        pw=st.text_input('Admin password',type='password')
        ok=st.form_submit_button('Sign in')
    if ok:
        expected=os.environ.get('ORGANISER_PASSWORD','')
        if len(expected)>=12 and pw==expected:
            token=create_admin_session()
            cookie_manager.set('ul_admin_session',token,expires_at=datetime.now()+timedelta(days=14))
            st.session_state['event_admin']=True
            st.rerun()
        else:
            st.error('Incorrect password or ORGANISER_PASSWORD is not securely configured.')
    st.stop()

if st.sidebar.button('Sign out'):
    token=admin_token
    if token:
        revoke_admin_session(token)
        try:
            cookie_manager.delete('ul_admin_session')
        except KeyError:
            pass
    st.session_state.pop('event_admin',None)
    st.rerun()

corpus=load_corpus()
labels={p['participant_id']:f"{p['participant_id']} — {p['title']}" for p in corpus}
tabs=st.tabs(['Live dashboard','Create team','Final submissions','Flag attempts & logs'])

@st.fragment(run_every='3s')
def live_dashboard():
    snap=admin_snapshot()
    cluster_options=['All clusters']+clusters()
    selected=st.selectbox('Filter dashboard by cluster',cluster_options,key='admin_dashboard_cluster')
    teams=[t for t in snap['teams'] if selected=='All clusters' or t['cluster']==selected]
    team_ids={t['team_id'] for t in teams}
    subs={k:v for k,v in snap['submissions'].items() if v['team_id'] in team_ids}
    finished=sum(len(t['completed_levels'])==4 for t in teams)
    a,b,c=st.columns(3)
    a.metric('Registered teams',len(teams))
    b.metric('Completed all levels',finished)
    c.metric('Locked submissions',len(subs))
    scores=[]
    for t in teams:
        ss=[v for v in subs.values() if v['team_id']==t['team_id']]
        flags=sum(10 for v in ss if v.get('flag_correct'))
        gp=next((v.get('graph_score',{}).get('points',0) for v in ss if v['level']==4),0)
        scores.append({'Team ID':t['team_id'],'Team':t['name'],'Cluster':t['cluster'],'Levels submitted':len(ss),'Flag points':flags,'Graph points':gp,'Total / 100':round(flags+gp,2)})
    st.subheader('Scoreboard')
    if scores:
        st.dataframe(pd.DataFrame(scores).sort_values('Total / 100',ascending=False),hide_index=True,use_container_width=True)
    else:
        st.info('No teams yet for this selection.')
    st.subheader('Team progress')
    if teams:
        st.dataframe(pd.DataFrame(teams),hide_index=True,use_container_width=True)
    else:
        st.info('No teams yet for this selection.')
    st.subheader('Latest activity')
    audit=[x for x in snap['audit'] if selected=='All clusters' or x.get('team_id') in team_ids]
    audit=audit[-20:]
    if audit:
        st.dataframe(pd.DataFrame(audit[::-1]),hide_index=True,use_container_width=True)
    else:
        st.caption('No activity yet.')

with tabs[0]:
    live_dashboard()

with tabs[1]:
    st.subheader('Register a participant team')
    available_clusters=clusters()
    if not available_clusters:
        st.error('No clusters are configured. Add rows to data/event_content.csv first.')
    else:
        st.markdown('**Create a new cluster**')
        st.caption('A new cluster starts as a copy of the selected template cluster. Edit its rows in data/event_content.csv to customise its papers, questions, answers and hints.')
        template=st.selectbox('Template cluster',available_clusters,key='cluster_template')
        new_cluster_name=st.text_input('New cluster name',key='new_cluster_name')
        if st.button('Create cluster'):
            try:
                created=create_cluster_from_template(new_cluster_name,template)
                st.success(f'Created cluster: {created}')
                st.rerun()
            except ValueError as e:
                st.error(str(e))
        st.divider()
        st.markdown('**Create team**')
        with st.form('create_team'):
            tid=st.text_input('Team ID')
            name=st.text_input('Team name')
            password=st.text_input('Initial password',type='password')
            selected_cluster=st.selectbox('Cluster',clusters(),key='team_cluster_select')
            ok=st.form_submit_button('Create team',type='primary')
        if ok:
            try:
                create_team(tid,name,password,selected_cluster)
                st.success(f'Created {tid.strip().upper()} in {selected_cluster}.')
            except ValueError as e:
                st.error(str(e))

@st.fragment(run_every='3s')
def submissions_view():
    snap=admin_snapshot()
    teams={t['team_id']:t for t in snap['teams']}
    options=['All clusters']+clusters()
    selected=st.selectbox('Filter submissions by cluster',options,key='admin_submissions_cluster')
    records=[]
    for key,rec in snap['submissions'].items():
        team=teams.get(rec['team_id'],{})
        if selected=='All clusters' or team.get('cluster')==selected:
            records.append((key,rec,team))
    st.subheader('Final submissions — all locked levels')
    if not records:
        st.info('No submissions yet for this selection.')
    for key,rec,team in sorted(records,key=lambda x:(x[1]['team_id'],x[1]['level'])):
        with st.expander(f"{rec['team_id']} · {team.get('cluster','')} · Level {rec['level']} · {rec['submitted_at']}"):
            st.write(f"**Flag submitted:** {rec.get('submitted_flag') or '(no flag entered)'}")
            st.write(f"**Flag correctness:** {'Correct' if rec.get('flag_correct') else 'Incorrect'}")
            st.write(f"**Graph edges:** {rec.get('edge_count',0)}")
            try:
                df=pd.read_csv(io.StringIO(rec['csv']),dtype=str,keep_default_na=False)
                df['Source paper']=df.source_id.map(labels)
                df['Target paper']=df.target_id.map(labels)
                st.dataframe(df[['Source paper','relationship_type','Target paper','evidence_reference']],hide_index=True,use_container_width=True)
                dot=['digraph G { graph [rankdir=LR, bgcolor="#ffffff", pad="0.25"];',
                     'node [shape=box, style="rounded,filled", fillcolor="#EAF2FF", color="#315A8A", fontcolor="#142B45", fontname="Arial", fontsize=10, penwidth=1.5];',
                     'edge [color="#2563EB", fontcolor="#173F7A", fontname="Arial", fontsize=9, penwidth=2, arrowsize=0.8];']
                for r in df.itertuples():
                    dot.append(f'"{r.source_id}" -> "{r.target_id}" [label="{r.relationship_type}"];')
                dot.append('}')
                st.graphviz_chart('\n'.join(dot),use_container_width=True)
            except Exception as e:
                st.error(f'Could not render graph: {e}')
            st.write('**Graph metrics:**',rec.get('graph_score',{}))
            st.download_button('Download submitted cumulative graph CSV',rec['csv'],f"{rec['team_id']}_level{rec['level']}.csv",'text/csv',key=f'dl_{key}')

with tabs[2]:
    submissions_view()

@st.fragment(run_every='3s')
def logs_view():
    snap=admin_snapshot()
    teams={t['team_id']:t for t in snap['teams']}
    options=['All clusters']+clusters()
    selected=st.selectbox('Filter activity by cluster',options,key='admin_logs_cluster')
    attempts=[]
    for key,items in snap['attempts'].items():
        team_id=key.split(':',1)[0]
        team=teams.get(team_id,{})
        if selected!='All clusters' and team.get('cluster')!=selected:
            continue
        for item in items:
            attempts.append({'Team / Level':key,'Cluster':team.get('cluster',''),'At':item['at'],'Answer':item['answer'],'Correct':item['correct']})
    st.subheader('All flag attempts')
    if attempts:
        st.dataframe(pd.DataFrame(attempts),hide_index=True,use_container_width=True)
    else:
        st.info('No flag attempts yet.')
    st.subheader('Audit log')
    audit=[x for x in snap['audit'] if selected=='All clusters' or (x.get('team_id') in teams and teams[x.get('team_id')].get('cluster')==selected)]
    if audit:
        st.dataframe(pd.DataFrame(audit[::-1]),hide_index=True,use_container_width=True)
    else:
        st.info('No audit events yet.')
    log=Path(__file__).parent/'data/realtime_events.jsonl'
    if log.exists():
        st.download_button('Download real-time event log (JSONL)',log.read_text(encoding='utf-8'),'realtime_events.jsonl','application/json')

with tabs[3]:
    logs_view()
