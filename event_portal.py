"""Participant portal for the incremental one-cluster graph challenge."""
from pathlib import Path
import io,html
import pandas as pd
import streamlit as st
import extra_streamlit_components as stx
from datetime import datetime, timedelta
from dotenv import load_dotenv
load_dotenv(Path(__file__).with_name('.env'))
from event_core import CLUSTER,LEVELS,levels_for_cluster,authenticate,create_session,authenticate_session,revoke_session,get_draft,save_draft,attempt_flag,flag_status,finalise,team_progress,load,released_papers
from challenge.participant_data import load_corpus,load_vocabulary,card_pdf_path
from scoring.graph_scorer import score_csv

st.set_page_config(page_title='Uncharted Literature · Participant',page_icon='🧭',layout='wide')
st.title('🧭 Uncharted Literature')
cookie_manager=stx.CookieManager(key='ul_participant_cookie')
cookies=cookie_manager.get_all()
if cookies is None:
 st.info('Restoring participant session…')
 st.stop()
def login():
 st.subheader('Participant login')
 with st.form('login'):
  tid=st.text_input('Team ID');pw=st.text_input('Password',type='password');ok=st.form_submit_button('Sign in',type='primary')
 if ok:
  user=authenticate(tid,pw)
  if user:
   token=create_session(user['team_id']);cookie_manager.set('ul_team_session',token,expires_at=datetime.now()+timedelta(days=14));st.session_state['event_team']=user;st.rerun()
  else:st.error('Invalid team ID or password.')
team=st.session_state.get('event_team')
if not team:
 token=(cookies.get('ul_team_session') if isinstance(cookies,dict) else None) or cookie_manager.get('ul_team_session')
 if token:team=authenticate_session(token);st.session_state['event_team']=team if team else None
if not team:login();st.stop()
st.caption(f"Cluster: {team['cluster']}")
team_levels=levels_for_cluster(team['cluster'])
completed,current=team_progress(team['team_id'])
with st.sidebar:
 st.success(f"{team['name']} · {team['team_id']}");st.markdown('### Level progress')
 for lv in team_levels:st.write(('✅' if lv['id'] in completed else ('🟡' if lv['id']==current else '🔒'))+f" Level {lv['id']}: {lv['title']}")
 if st.button('Sign out'):
  revoke_session((cookies.get('ul_team_session') if isinstance(cookies,dict) else None) or cookie_manager.get('ul_team_session'))
  try:
   cookie_manager.delete('ul_team_session')
  except KeyError:
   pass
  st.session_state.pop('event_team',None);st.rerun()
if current is None:st.success(f'All {len(team_levels)} levels completed.');st.stop()
section=st.radio('Navigate',['Start Here','Corpus','Vocabulary','Graph Builder','Flag','Submission'],horizontal=True,label_visibility='collapsed',key=f"nav_{team['team_id']}_{current}")
corpus=load_corpus();vocab=load_vocabulary();available=released_papers(current,team['cluster']);papers=[p for p in corpus if p['participant_id'] in available]
byid={p['participant_id']:p for p in corpus};labels={p['participant_id']:f"{p['participant_id']} — {p['title']}" for p in corpus}
spec=next(x for x in team_levels if x['id']==current);key=f"{team['team_id']}:{current}"
if section=='Start Here':
 st.header('How the challenge works');st.write('Build one cumulative knowledge graph across all four levels. New papers are released at each level; your team can connect any two distinct papers already released.');st.write(f"**Current level:** {current} — {spec['title']}");st.write(f"**Papers currently released:** {len(available)} of {sum(len(x['paper_ids']) for x in team_levels)}");st.write('Submit at least one flag attempt and your cumulative graph to lock the current level and unlock the next one. The flag may be correct or incorrect.')
elif section=='Corpus':
 st.header('Released papers')
 for lv in team_levels:
  level_papers=[p for p in papers if p['participant_id'] in lv['paper_ids']]
  if not level_papers:
   continue
  st.subheader(f"Level {lv['id']} — {lv['title']}")
  for p in level_papers:
   with st.expander(f"{p['participant_id']} — {p['title']}"):
    st.write(p.get('citation',''));st.write(p.get('abstract',''));url=p.get('open_access_url') or p.get('doi_url')
    if url:st.markdown(f'[Open paper]({url})')
    card=card_pdf_path(p['participant_id'])
    if card.exists():st.download_button('Download challenge card PDF',card.read_bytes(),f"{p['participant_id']}_challenge_card.pdf",'application/pdf',key=f"card_{team['team_id']}_{p['participant_id']}")
elif section=='Vocabulary':
 st.header('Accepted relationship types');st.dataframe(pd.DataFrame(vocab['relationship_types']),hide_index=True,use_container_width=True)
elif section=='Graph Builder':
 st.header(f'Graph Builder · Level {current}');st.caption(f"{len(available)} papers released. You may connect any two different released papers.")
 prior=load()['submissions'].get(f"{team['team_id']}:{current-1}") if current>1 else None
 locked=pd.read_csv(io.StringIO(prior['csv']),dtype=str,keep_default_na=False) if prior and prior.get('csv','').strip() else pd.DataFrame(columns=['source_id','target_id','relationship_type','evidence_reference'])
 olddraft=get_draft(team['team_id'],current)
 if f'graph_df_{team["team_id"]}_{current}' not in st.session_state:
  st.session_state[f'graph_df_{team["team_id"]}_{current}']=pd.read_csv(io.StringIO(olddraft),dtype=str,keep_default_na=False) if olddraft.strip() else locked.copy()
 statekey=f'graph_df_{team["team_id"]}_{current}';df=st.session_state[statekey]
 rels=[r['relationship_type'] for r in vocab['relationship_types']]
 with st.form(f'add_edge_{current}',clear_on_submit=True):
  c1,c2=st.columns(2);src=c1.selectbox('Source paper',available,format_func=lambda x:labels[x]);dst=c2.selectbox('Target paper',available,format_func=lambda x:labels[x]);rel=st.selectbox('Relationship type',rels);evidence=st.text_input('Evidence reference',placeholder='P02, page 4, Section 3');add=st.form_submit_button('Add edge',type='primary')
 if add:
  if src==dst:st.error('A paper cannot be connected to itself.')
  elif not evidence.strip():st.error('Add an evidence reference.')
  else:
   st.session_state[statekey]=pd.concat([df,pd.DataFrame([{'source_id':src,'target_id':dst,'relationship_type':rel,'evidence_reference':evidence.strip()}])],ignore_index=True);save_draft(team['team_id'],current,st.session_state[statekey].to_csv(index=False));st.rerun()
 df=st.session_state[statekey].copy()
 if not locked.empty:
  locked_keys=set(tuple(x) for x in locked[['source_id','target_id','relationship_type','evidence_reference']].fillna('').values.tolist())
 else:locked_keys=set()
 st.subheader('Cumulative edge table')
 display=df.copy();display['Source paper']=display['source_id'].map(labels);display['Target paper']=display['target_id'].map(labels);display['Locked']=display.apply(lambda r:tuple(r[['source_id','target_id','relationship_type','evidence_reference']].fillna('').tolist()) in locked_keys,axis=1)
 st.dataframe(display[['Source paper','relationship_type','Target paper','evidence_reference','Locked']],hide_index=True,use_container_width=True)
 deletable=[i for i,r in df.iterrows() if tuple(r[['source_id','target_id','relationship_type','evidence_reference']].fillna('').tolist()) not in locked_keys]
 if deletable:
  chosen=st.selectbox('Select a current-level edge to delete',deletable,format_func=lambda i:f"{labels.get(df.loc[i,'source_id'],df.loc[i,'source_id'])} → {labels.get(df.loc[i,'target_id'],df.loc[i,'target_id'])} ({df.loc[i,'relationship_type']})")
  if st.button('Delete selected edge'):st.session_state[statekey]=df.drop(index=chosen).reset_index(drop=True);save_draft(team['team_id'],current,st.session_state[statekey].to_csv(index=False));st.rerun()
 else:st.caption('No deletable current-level edges. Previous-level edges are locked.')
 st.subheader('Live graph diagram')
 if not df.empty:
  dot=['digraph G { graph [rankdir=LR, bgcolor="#ffffff", pad="0.25"]; node [shape=box, style="rounded,filled", fillcolor="#EAF2FF", color="#315A8A", fontcolor="#142B45", fontname="Arial", fontsize=10, penwidth=1.5]; edge [color="#2563EB", fontcolor="#173F7A", fontname="Arial", fontsize=9, penwidth=2, arrowsize=0.8];']
  for pid in available:dot.append(f'"{pid}" [label="{pid}\\n{html.escape(byid[pid]["title"][:52])}"];')
  for _,r in df.iterrows():
   typ=r['relationship_type'];style='dir=none' if typ in ('SHARES_PRINCIPLE','ANALOGOUS_PROBLEM') else 'dir=forward';dot.append(f'"{r["source_id"]}" -> "{r["target_id"]}" [label="{typ}", {style}];')
  dot.append('}');st.graphviz_chart('\n'.join(dot),use_container_width=True)
 else:st.info('Add the first relationship to see the graph diagram.')
 csv_text=df.to_csv(index=False);parsed,_=score_csv(csv_text, allow_any_pair=True)
 if parsed.errors:st.error('Graph validation issues:\n'+'\n'.join(parsed.errors))
 else:st.success(f'{len(df)} graph edges in current cumulative graph.')
 st.download_button('Download cumulative graph CSV',csv_text,f"{team['team_id']}_level{current}.csv",'text/csv')
 if st.button('Save graph draft',type='primary'):save_draft(team['team_id'],current,csv_text);st.success('Draft saved.')
elif section=='Flag':
 st.header(f'Flag · Level {current}');st.write(spec['question']);fs=flag_status(team['team_id'],current)
 if fs['last']:
  st.success('Most recent flag is correct.' if fs['last']['correct'] else 'Most recent flag is incorrect.')
 with st.form(f'flag_{current}'):
  answer=st.text_input('Your flag answer');check=st.form_submit_button('Check flag')
 if check:
  result=attempt_flag(team['team_id'],current,answer);st.success(result['message']) if result['correct'] else st.error(result['message']);st.rerun()
 st.caption(f"Attempts: {fs['attempts']}. At least one attempt is required to advance; a correct answer is not required.")
 with st.expander('Hints'):
  for i,h in enumerate(spec['hints'],1):st.write(f'**Hint {i}.** {h}')
elif section=='Submission':
 st.header(f'Submit level {current}');d=load();rec=d['submissions'].get(key)
 if rec:st.success('This level is already locked.');st.stop()
 draft=get_draft(team['team_id'],current)
 if not draft.strip():st.warning('Add or save at least one graph edge before submitting.');st.stop()
 parsed,result=score_csv(draft, allow_any_pair=True)
 if parsed.errors:st.error('Fix graph validation errors before submitting.');st.write('\n'.join(parsed.errors));st.stop()
 fs=flag_status(team['team_id'],current);flag=fs['last']['answer'] if fs['last'] else ''
 if fs['attempts']==0:
  st.warning('You must submit at least one flag attempt in the Flag tab before advancing. The answer can be incorrect.')
  st.stop()
 st.write(f"**Cluster:** {team['cluster']}");st.write(f'**Level:** {current} — {spec["title"]}');st.write(f'**Submitted flag:** {flag or "No flag attempted"}');st.write(f'**Flag status:** {"Correct" if fs["correct"] else "Incorrect / not solved"}');st.write(f'**Cumulative graph edges:** {len(parsed.edges)}')
 df=pd.read_csv(io.StringIO(draft),dtype=str,keep_default_na=False);df['Source paper']=df.source_id.map(labels);df['Target paper']=df.target_id.map(labels);st.dataframe(df[['Source paper','relationship_type','Target paper','evidence_reference']],hide_index=True,use_container_width=True)
 if not df.empty:
  dot=['digraph G { graph [rankdir=LR, bgcolor="#ffffff", pad="0.25"]; node [shape=box,style="rounded,filled",fillcolor="#EAF2FF",color="#315A8A",fontcolor="#142B45",fontname="Arial",penwidth=1.5]; edge [color="#2563EB",fontcolor="#173F7A",fontname="Arial",fontsize=9,penwidth=2];']+[f'"{r.source_id}" -> "{r.target_id}" [label="{r.relationship_type}"];' for r in df.itertuples()]+['}'];st.graphviz_chart('\n'.join(dot),use_container_width=True)
 confirm=st.checkbox('We have reviewed this cumulative graph and want to lock this level.',key=f"confirm_{team['team_id']}_{current}")
 if st.button('Submit and unlock next level',type='primary',disabled=not confirm):
  metrics=result.organiser_view()['public'];points=round(metrics['weighted_f1']*60,2) if current==4 else 0
  try:
   finalise(team['team_id'],current,draft,fs['correct'],{'weighted_f1':metrics['weighted_f1'],'weighted_precision':metrics['weighted_precision'],'recall':metrics['recall'],'points':points,'edges':len(parsed.edges)},flag)
   st.session_state.pop(f'graph_df_{team["team_id"]}_{current}',None)
   st.success('Submitted. This level is locked and the next level is unlocked.')
   st.rerun()
  except (ValueError,PermissionError) as e:
   st.error(str(e))
