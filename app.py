"""TTOPULO: personal quiz books, email login, PDF extraction, study/test modes."""
import hashlib
import json
import re
from pathlib import Path

import streamlit as st
from cloud import CloudError, config, login, signup, logout, db, list_books, questions, progress, add_book, upsert_progress, delete_progress
from parser import extract_pdf

st.set_page_config(page_title='또풀어 | TTOPULO',page_icon='📖',layout='wide',initial_sidebar_state='collapsed')
st.markdown('''<style>
.stApp, [data-testid="stAppViewContainer"] {background:#fff;color:#17233b}
.block-container {max-width:1150px;padding-top:2.5rem;padding-bottom:4rem}
h1,h2,h3 {letter-spacing:-.035em}
.stButton button {border-radius:9px;min-height:40px}
[data-testid="stMetric"] {border:1px solid #e2e8f0;padding:12px;border-radius:12px}
/* Native Streamlit button label visibility, including iPad Safari. */
.stButton button[kind="secondary"] {background:white!important;border:1px solid #cbd5e1!important}
.stButton button[kind="secondary"] p,.stButton button[kind="secondary"] span {color:#111827!important;-webkit-text-fill-color:#111827!important}
.stButton button[kind="primary"] {background:#2563eb!important}
.stButton button[kind="primary"] p,.stButton button[kind="primary"] span {color:white!important;-webkit-text-fill-color:white!important}
</style>''',unsafe_allow_html=True)


def api(action, *args, **kwargs):
    try:
        return action(*args, **kwargs)
    except CloudError as err:
        st.error(str(err))
        st.stop()


def auth_page():
    st.title('📖 또풀어')
    st.caption('TTOPULO · 한 번 배우고, 또 풀어.')
    st.write('각자의 PDF 문제집을 등록하고, 노트북과 아이패드에서 이어서 공부해 봐.')
    a,b=st.columns([1,1.25],gap='large')
    with a:
        with st.container(border=True):
            tab1,tab2=st.tabs(['로그인','회원가입'])
            with tab1:
                with st.form('login'):
                    email=st.text_input('이메일',key='login_email').strip()
                    password=st.text_input('비밀번호',type='password',key='login_password')
                    submitted=st.form_submit_button('로그인',type='primary',use_container_width=True)
                if submitted:
                    try:
                        login(email,password)
                        st.rerun()
                    except CloudError as err:
                        st.error(f'로그인 실패: {err}')
            with tab2:
                with st.form('signup'):
                    email=st.text_input('이메일',key='signup_email').strip()
                    password=st.text_input('비밀번호 (6자 이상)',type='password',key='signup_password')
                    submitted=st.form_submit_button('계정 만들기',use_container_width=True)
                if submitted:
                    if len(password)<6:
                        st.warning('비밀번호를 6자 이상 입력해 줘.')
                    else:
                        try:
                            result=signup(email,password)
                            if result.get('access_token'):
                                st.rerun()
                            else:
                                st.success('가입 요청이 완료됐어. 이메일 확인 링크가 오면 인증한 다음 로그인해 줘.')
                        except CloudError as err:
                            st.error(f'가입 실패: {err}')
    with b:
        st.subheader('문제집은 계정별로 비공개')
        st.write('✅ PDF 자동 문제 인식\n\n✅ 정답·해설 공개 학습 모드\n\n✅ 자동 채점 실전 모드\n\n✅ 번호별 이동과 학습 진행 기록')
        st.info('앱에 가입해도 다른 사용자의 문제집은 볼 수 없어. 데이터베이스에서 사용자별 접근을 제한해.')


def state_go(view,book=None):
    st.session_state['view']=view
    if book is not None:
        st.session_state['active_book']=book
    st.session_state['current_question']=0
    st.rerun()


def book_data(book_id):
    qs=api(questions,book_id)
    rows=api(progress,book_id)
    done={r['question_id']:r for r in rows}
    for q in qs:
        p=done.get(q['id'],{})
        q['learned']=bool(p.get('learned'))
        q['submitted_answer']=p.get('submitted_answer')
        q['is_correct']=p.get('is_correct')
    return qs


def grade(q,label):
    idx=q['answer_indices'] or []
    opts=q['options'] or []
    if q['needs_review'] or len(idx)!=1 or not isinstance(idx[0],int) or idx[0]<0 or idx[0]>=len(opts):
        return None
    return label==opts[idx[0]]['label']


def explain(q):
    if q['needs_review']:
        st.warning('⚠️ 원본에 정답 오류 또는 검토 의견이 있어 자동 채점을 보류했어.')
    st.success('정답(원문): '+(q['answer_text'] or '정답 없음'))
    st.markdown('**해설 / 피드백**')
    st.write(q['explanation'] or '원본에 해설이 없어.')
    if q['notes']:
        st.info('검토 메모: '+q['notes'])


def nums(qs,index,learning,book_id):
    st.markdown('**문제 선택**')
    st.caption('네모를 누르면 해당 번호로 이동해.')
    # The CSS ::after draws black digits even on browser/theme variants where
    # Streamlit hides the button's own text.
    css=[]
    for i,q in enumerate(qs):
        ident=f'nav_{"l" if learning else "t"}_{q["id"].replace("-", "_")}'
        selected=i==index
        css.append(f'''.st-key-{ident} button{{position:relative!important;min-height:42px!important;
          padding:0!important;border:1px solid {'#2563eb' if selected else '#cbd5e1'}!important;
          background:{'#dbeafe' if selected else '#fff'}!important}}
          .st-key-{ident} button::after{{content:"{i+1}";position:absolute;inset:0;
          display:flex;align-items:center;justify-content:center;pointer-events:none;
          color:#111827!important;font-size:14px;font-weight:700}}
          .st-key-{ident} button p{{visibility:hidden!important}}''')
    st.markdown('<style>'+''.join(css)+'</style>',unsafe_allow_html=True)
    for start in range(0,len(qs),5):
        cols=st.columns(5,gap='small')
        for i in range(start,min(start+5,len(qs))):
            with cols[i-start]:
                q=qs[i]
                ident=f'nav_{"l" if learning else "t"}_{q["id"].replace("-", "_")}'
                if st.button(str(i+1),key=ident,use_container_width=True,
                             help=f'{i+1}번'):
                    if learning:
                        api(upsert_progress,book_id,qs[index]['id'],learned=True)
                    st.session_state['current_question']=i
                    st.rerun()
    st.divider()
    st.markdown(f'**현재 문제: {index+1}/{len(qs)}**')
    st.progress((index+1)/len(qs))
    done=sum(bool(q['learned']) if learning else q['submitted_answer'] is not None for q in qs)
    st.caption(f'누적 {"학습" if learning else "실전 풀이"} 완료: {done}/{len(qs)}')
    with st.expander('진행 기록 초기화'):
        ok=st.checkbox('현재 문제집의 기록 초기화 확인',key=f'confirm_{book_id}_{learning}')
        if st.button('기록 초기화',disabled=not ok,key=f'reset_{book_id}_{learning}'):
            api(delete_progress,book_id,'learn' if learning else 'test')
            st.session_state['current_question']=0
            st.rerun()


def study_page(book,learning):
    book_id=book['id']; qs=book_data(book_id)
    if not qs:
        st.warning('등록된 문제가 없어.')
        if st.button('문제집 목록'):state_go('library')
        return
    st.title(book['title'])
    if st.button('← 문제집 목록으로',key='back'):
        state_go('library')
    st.caption('📘 학습 모드 · 정답·해설을 보면서 선택해 봐.' if learning else
               '✍️ 실전 모드 · 답을 선택하고 채점한 뒤 해설을 확인해 봐.')
    idx=min(max(int(st.session_state.get('current_question',0)),0),len(qs)-1)
    left,right=st.columns([1.1,3.0],gap='large')
    with left:
        with st.container(border=True):
            nums(qs,idx,learning,book_id)
    with right:
        q=qs[idx]
        st.markdown(f'**{q["section"]} · 문제 {q["number"]}**')
        st.markdown('#### '+q['prompt'])
        opts=q['options'] or []
        labels=[o['label'] for o in opts]
        desc={o['label']: f'{o["label"]} {o["text"]}' for o in opts}
        if learning:
            choice=st.radio('정답을 선택해 봐',labels,index=None,
                            format_func=lambda v:desc[v],key=f'learn_{q["id"]}')
            if choice:
                correct=grade(q,choice)
                if correct is None:st.info('정답 검토가 필요한 문제야.')
                elif correct:st.success('정답이야!')
                else:st.warning('선택한 답이 정답과 달라.')
            explain(q)
        else:
            existing=q['submitted_answer']
            with st.form(f'exam_{q["id"]}'):
                choice=st.radio('답 선택',labels,index=labels.index(existing) if existing in labels else None,
                                format_func=lambda v:desc[v])
                send=st.form_submit_button('채점하고 해설 보기',type='primary')
            if send:
                if not choice:
                    st.warning('먼저 답을 선택해 줘.')
                else:
                    api(upsert_progress,book_id,q['id'],submitted_answer=choice,is_correct=grade(q,choice))
                    st.rerun()
            if existing is not None:
                if q['is_correct'] is None:st.warning('검토할 문제라 자동 채점하지 않았어.')
                elif q['is_correct']:st.success('정답이야!')
                else:st.error('오답이야.')
                explain(q)
        st.divider()
        col1,col2=st.columns(2)
        with col1:
            if st.button('← 이전 문제',disabled=idx==0,use_container_width=True):
                if learning:api(upsert_progress,book_id,q['id'],learned=True)
                st.session_state['current_question']=idx-1;st.rerun()
        with col2:
            label=('학습 완료 표시 ✓' if learning else '마지막 문제') if idx==len(qs)-1 else '다음 문제 →'
            if st.button(label,disabled=(not learning and idx==len(qs)-1),
                         type='primary',use_container_width=True):
                if learning:api(upsert_progress,book_id,q['id'],learned=True)
                st.session_state['current_question']=min(idx+1,len(qs)-1)
                st.rerun()
        learned=sum(bool(q['learned']) for q in qs)
        # On the last question the DB was just updated, so rerun to reflect it.
        if learning and learned==len(qs):
            st.success('🎉 전체 학습을 완료했어. 이제 실전 모드를 시작할 수 있어!')
            if st.button('실전 모드 시작 →',type='primary',use_container_width=True):
                state_go('test',book_id)


def library_page():
    top,action=st.columns([4,1])
    with top:
        st.title('📖 내 문제집')
        st.caption('각자의 문제집과 학습 기록이 계정별로 보관돼.')
    with action:
        st.caption(st.session_state.get('auth_email') or '')
        if st.button('로그아웃',use_container_width=True):
            logout();st.rerun()
    items=api(list_books)
    if not items:st.info('아직 등록한 문제집이 없어. 아래에서 PDF를 추가해 줘.')
    for book in items:
        qs=book_data(book['id'])
        count=len(qs)
        learned=sum(bool(q['learned']) for q in qs)
        attempted=sum(q['submitted_answer'] is not None for q in qs)
        correct=sum(q['is_correct'] is True for q in qs)
        reviewed=sum(q['is_correct'] is not None for q in qs)
        with st.container(border=True):
            a,b=st.columns([3,1.2],gap='large')
            with a:
                st.markdown('### 📚 '+book['title'])
                st.caption(f'{count}문제 · 학습 완료 {learned}/{count} · 실전 풀이 {attempted}/{count}')
                if count: st.progress(learned/count)
                if attempted:st.caption(f'실전 정답 {correct}/{reviewed} (자동 채점 가능한 문항 기준)')
            with b:
                if st.button('📘 학습 모드',key='learn_'+book['id'],use_container_width=True):
                    state_go('learn',book['id'])
                ready=count>0 and learned==count
                if st.button('✍️ 실전 모드',key='test_'+book['id'],disabled=not ready,
                             type='primary',use_container_width=True):
                    state_go('test',book['id'])
                if not ready:st.caption('학습 완료 후 이용 가능')
                if st.button('⚙️ 관리',key='manage_'+book['id'],use_container_width=True):
                    state_go('manage',book['id'])
    st.divider()
    st.subheader('새 PDF 문제집 등록')
    file=st.file_uploader('문제가 포함된 PDF',type=['pdf'],key='upload')
    if file:
        payload=file.getvalue()
        fingerprint=hashlib.sha256(payload).hexdigest()
        existing=next((b for b in items if b['source_hash']==fingerprint),None)
        if existing:st.info(f'이미 「{existing["title"]}」에 등록된 파일이야.')
        else:
            title=st.text_input('문제집 이름',value=Path(file.name).stem.replace(' 기말고사 퀴즈',' 문제집').replace(' 퀴즈',' 문제집'))
            try:
                parsed=extract_pdf(payload)
                st.success(f'문제 후보 {len(parsed)}개 인식했어.')
                st.caption('문제집 등록 전에 정답과 선지를 확인해 줘. 오류가 있는 원문은 검토 필요로 표시돼.')
                for q in parsed:
                    with st.expander(f'{"⚠️ " if q["needs_review"] else ""}{q["section"]} · {q["number"]}번 · {q["prompt"][:45]}'):
                        st.write(q['prompt'])
                        for o in q['options']:st.write(o['label']+' '+o['text'])
                        st.write('**정답:** '+(q['answer_text'] or '미기재'))
                        st.write('**해설:** '+(q['explanation'] or '미기재'))
                        if q['notes']:st.warning(q['notes'])
                if st.button('이 문제집 저장',type='primary',disabled=not parsed or not title.strip()):
                    api(add_book,title.strip(),file.name,fingerprint,parsed)
                    st.success('문제집을 등록했어!');st.rerun()
            except Exception as exc:
                st.error(f'PDF를 읽지 못했어: {exc}')
    st.caption('PDF는 문제 추출에만 사용하고, 원본 PDF 파일 자체를 서버에 보관하지 않아.')


def management(book):
    if st.button('← 문제집 목록'):state_go('library')
    st.title('⚙️ 문제집 관리')
    name=st.text_input('문제집 이름',value=book['title'])
    if st.button('이름 변경 저장') and name.strip():
        api(db,'PATCH','quiz_books',{'id':f'eq.{book["id"]}'},{'title':name.strip()})
        st.rerun()
    for q in book_data(book['id']):
        with st.expander(f'{q["section"]} · {q["number"]}번 {"⚠️" if q["needs_review"] else ""}'):
            with st.form('edit_'+q['id']):
                prompt=st.text_area('문제',value=q['prompt'])
                raw=st.text_area('선지 (한 줄에 하나)',value='\n'.join(o['label']+' '+o['text'] for o in q['options']))
                answer=st.text_input('정답(원문)',value=q['answer_text'])
                explanation=st.text_area('해설',value=q['explanation'])
                notes=st.text_area('검토 의견',value=q['notes'])
                flagged=st.checkbox('정답 검토 필요',value=q['needs_review'])
                save=st.form_submit_button('수정 저장')
            if save:
                new_opts=[]
                for line in raw.splitlines():
                    match=re.match(r'^([①②③④⑤⑥⑦⑧⑨⑩])\s*(.*)',line.strip())
                    if match:new_opts.append({'label':match.group(1),'text':match.group(2)})
                letters='①②③④⑤⑥⑦⑧⑨⑩'
                indices=list(dict.fromkeys(letters.index(c) for c in re.findall('['+letters+']',answer)))
                if len(new_opts)<2:st.warning('선지를 2개 이상 입력해 줘.')
                else:
                    api(db,'PATCH','quiz_questions',{'id':f'eq.{q["id"]}'},
                        {'prompt':prompt,'options':new_opts,'answer_text':answer,
                         'answer_indices':indices,'explanation':explanation,
                         'notes':notes,'needs_review':flagged or len(indices)!=1})
                    api(db,'DELETE','quiz_progress',{'question_id':f'eq.{q["id"]}'})
                    st.rerun()
            verify=st.checkbox('이 문제 삭제 확인',key='delconfirm_'+q['id'])
            if st.button('문제 삭제',key='del_'+q['id'],disabled=not verify):
                api(db,'DELETE','quiz_questions',{'id':f'eq.{q["id"]}'})
                st.rerun()
    qs=book_data(book['id'])
    export=[{k:q[k] for k in ('section','number','prompt','options','answer_text','answer_indices','explanation','notes','needs_review','page')} for q in qs]
    st.download_button('문제집 JSON 백업',json.dumps(export,ensure_ascii=False,indent=2),
                       file_name='ttopulo_backup.json',mime='application/json')
    st.divider()
    confirm=st.checkbox('이 문제집과 학습 기록을 모두 삭제하는 데 동의해')
    if st.button('문제집 전체 삭제',disabled=not confirm):
        api(db,'DELETE','quiz_books',{'id':f'eq.{book["id"]}'})
        state_go('library')


try:
    config()
except CloudError as exc:
    st.error(str(exc))
    st.info('README.md를 보고 Supabase 프로젝트를 연결한 다음 다시 실행해 줘.')
    st.stop()

if not st.session_state.get('auth_access'):
    auth_page()
    st.stop()
if not st.session_state.get('auth_uid'):
    logout()
    st.rerun()
view=st.session_state.get('view','library')
if view=='library':library_page()
else:
    item=next((b for b in api(list_books) if b['id']==st.session_state.get('active_book')),None)
    if not item:
        st.warning('선택한 문제집을 찾을 수 없어.')
        if st.button('문제집 목록'):state_go('library')
    elif view=='learn':study_page(item,True)
    elif view=='test':
        qs=book_data(item['id'])
        if qs and all(q['learned'] for q in qs):study_page(item,False)
        else:
            st.warning('학습 모드를 완료한 후 실전 모드로 이동할 수 있어.')
            if st.button('학습 모드로'):state_go('learn',item['id'])
    elif view=='manage':management(item)
    else:state_go('library')
