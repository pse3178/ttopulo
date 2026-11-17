"""TTOPULO: personal quiz books, email login, PDF extraction, study/test modes."""
import hashlib
import json
import re
from pathlib import Path

import streamlit as st
from cloud import CloudError, config, login, signup, logout, db, list_books, questions, progress, add_book, upsert_progress, delete_progress
from parser import extract_pdf
from ocr_parser import extract_scanned_pdf, ocr_available
import fitz

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
        q['bookmarked']=bool(p.get('bookmarked',False))
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
    st.caption('네모를 누르면 해당 번호로 이동해. 빨간 테두리 = 나중에 다시 볼 문제')
    bookmarked=sum(bool(q.get('bookmarked')) for q in qs)
    if bookmarked:
        st.caption(f'🔖 다시 볼 문제 {bookmarked}개')
    # The CSS ::after draws black digits even on browser/theme variants where
    # Streamlit hides the button's own text.
    css=[]
    for i,q in enumerate(qs):
        ident=f'nav_{"l" if learning else "t"}_{q["id"].replace("-", "_")}'
        selected=i==index
        marked=bool(q.get('bookmarked'))
        border_color='#dc2626' if marked else ('#2563eb' if selected else '#cbd5e1')
        border_size='3px' if marked else '1px'
        button_bg='#fee2e2' if (marked and selected) else '#fff7f7' if marked else '#dbeafe' if selected else '#fff'
        css.append(f'''.st-key-{ident} button{{position:relative!important;min-height:42px!important;
          padding:0!important;border:{border_size} solid {border_color}!important;
          background:{button_bg}!important}}
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
        title_col, mark_col = st.columns([3, 2], gap='small')
        with title_col:
            st.markdown(f'**{q["section"]} · 문제 {q["number"]}**')
        with mark_col:
            is_marked=bool(q.get('bookmarked'))
            label='🔖 다시 보기 해제' if is_marked else '🔖 나중에 다시 보기'
            bkey=f'bookmark_{q["id"]}'
            st.markdown(f'<style>.st-key-{bkey} button{{color:#b91c1c!important;border:2px solid #ef4444!important;background:#fff1f2!important}}.st-key-{bkey} button p{{color:#b91c1c!important;-webkit-text-fill-color:#b91c1c!important}}</style>',unsafe_allow_html=True)
            if st.button(label,key=bkey,use_container_width=True,
                         help='이 문제의 번호표에 빨간 테두리를 표시하거나 해제합니다.'):
                api(upsert_progress,book_id,q['id'],bookmarked=not is_marked)
                st.rerun()
        if q.get('bookmarked'):
            st.caption('🔴 다시 볼 문제로 표시했어. 왼쪽 번호표가 빨간색으로 보여.')
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
    st.subheader('ChatGPT에서 변환한 문제집(JSON) 등록')
    st.caption('ChatGPT에서 만든 또풀어용 JSON 파일을 올리면 PDF를 다시 만들 필요 없이 바로 문제집으로 등록할 수 있어.')
    json_upload=st.file_uploader('또풀어 문제집 JSON 파일',type=['json'],key='json_upload')
    if json_upload is not None:
        try:
            raw_data=json_upload.getvalue()
            if len(raw_data)>3_000_000:
                raise ValueError('JSON 파일이 너무 커. 3MB 이하로 나누어 올려줘.')
            data=json.loads(raw_data.decode('utf-8-sig'))
            if isinstance(data,list):
                title_default=Path(json_upload.name).stem
                imported=data
            elif isinstance(data,dict):
                title_default=str(data.get('title') or Path(json_upload.name).stem)
                imported=data.get('questions')
            else:
                raise ValueError('JSON 최상위에는 questions 목록 또는 문제 목록이 필요해.')
            if not isinstance(imported,list) or not 1<=len(imported)<=500:
                raise ValueError('questions에는 문제 1~500개가 필요해.')
            checked=[]
            for pos,item in enumerate(imported,1):
                if not isinstance(item,dict):
                    raise ValueError(f'{pos}번째 문제 형식이 올바르지 않아.')
                prompt=item.get('prompt')
                options=item.get('options')
                if not isinstance(prompt,str) or not prompt.strip() or len(prompt)>10000:
                    raise ValueError(f'{pos}번째 문제의 문장을 확인해 줘.')
                if not isinstance(options,list) or not 2<=len(options)<=10:
                    raise ValueError(f'{pos}번째 문제의 선지가 2~10개인지 확인해 줘.')
                normalized=[]
                for oi,option in enumerate(options):
                    if not isinstance(option,dict):
                        raise ValueError(f'{pos}번째 문제의 선지 형식이 올바르지 않아.')
                    label='①②③④⑤⑥⑦⑧⑨⑩'[oi]
                    optext=option.get('text')
                    if option.get('label')!=label or not isinstance(optext,str) or not optext.strip() or len(optext)>2000:
                        raise ValueError(f'{pos}번째 문제의 {label}번 선지를 확인해 줘.')
                    normalized.append({'label':label,'text':optext.strip()})
                indices=item.get('answer_indices',[])
                if not isinstance(indices,list) or any(type(i)!=int or i<0 or i>=len(normalized) for i in indices) or len(indices)>1:
                    raise ValueError(f'{pos}번째 문제의 정답 번호를 확인해 줘.')
                answer_label=normalized[indices[0]]['label'] if indices else ''
                needs_review=bool(item.get('needs_review',False)) or not indices
                checked.append({
                    'section':str(item.get('section') or '미분류')[:100],
                    'number':int(item.get('number',pos)),
                    'page':int(item.get('page',1)),
                    'prompt':prompt.strip(),
                    'options':normalized,
                    'answer_text':answer_label,
                    'answer_indices':indices,
                    'explanation':str(item.get('explanation') or '')[:20000],
                    'notes':str(item.get('notes') or '')[:2000],
                    'needs_review':needs_review,
                })
            fingerprint=hashlib.sha256(raw_data).hexdigest()
            already=next((b for b in items if b['source_hash']==fingerprint),None)
            if already:
                st.info(f'이미 「{already["title"]}」에 등록된 JSON 파일이야.')
            else:
                st.success(f'JSON 문제 {len(checked)}개를 읽었어.')
                st.warning('PDF에서 변환한 문제는 반드시 원본과 비교해 줘. 검토가 필요한 문제는 자동 채점을 보류해.')
                for item in checked[:8]:
                    with st.expander(f'{item["number"]}번 · {item["prompt"][:38]}'):
                        st.write(item['prompt'])
                        for opt in item['options']:
                            st.write(opt['label']+' '+opt['text'])
                        st.write('정답: '+(item['answer_text'] or '미확인'))
                        st.write('해설: '+(item['explanation'] or '없음'))
                        if item['needs_review']:st.warning('정답 검토 필요')
                if len(checked)>8:st.caption(f'미리보기는 앞의 8문제만 표시해. 전체 {len(checked)}문제가 저장돼.')
                json_title=st.text_input('JSON 문제집 이름',value=title_default[:150],key='json_title')
                if st.button('JSON 문제집 저장',type='primary',disabled=not json_title.strip()):
                    api(add_book,json_title.strip(),json_upload.name,fingerprint,checked)
                    st.success('JSON 문제집을 저장했어!')
                    st.rerun()
        except (ValueError,TypeError,UnicodeError,json.JSONDecodeError) as exc:
            st.error(f'JSON 파일을 확인해 줘: {exc}')
    st.divider()
    st.subheader('새 PDF 문제집 등록')
    file=st.file_uploader('문제가 포함된 PDF',type=['pdf'],key='upload')
    if file:
        payload=file.getvalue()
        base_hash=hashlib.sha256(payload).hexdigest()
        mode=st.radio('PDF 인식 방식', ['일반 PDF (텍스트 추출)', '스캔 PDF (한국어 OCR)'],horizontal=True)
        scanned=mode.startswith('스캔')
        page_start=1;page_end=1
        if scanned:
            page_count=len(fitz.open(stream=payload,filetype='pdf'))
            st.info(f'이 파일은 {page_count}페이지야. 스캔 인식은 서버 부담을 줄이기 위해 한 번에 최대 12페이지씩 처리해.')
            l,r=st.columns(2)
            with l:page_start=st.number_input('시작 페이지',min_value=1,max_value=page_count,value=1,step=1)
            with r:page_end=st.number_input('끝 페이지',min_value=page_start,max_value=min(page_count,page_start+11),value=min(page_count,page_start+4),step=1)
            st.caption('PDF 페이지 번호 기준이야. 1~5페이지를 저장한 다음 6~10페이지를 다른 문제집으로 등록할 수 있어.')
        fingerprint=hashlib.sha256((base_hash+f':{mode}:{page_start}:{page_end}').encode()).hexdigest() if scanned else base_hash
        existing=next((b for b in items if b['source_hash']==fingerprint),None)
        if existing:
            st.info(f'이미 「{existing["title"]}」에 등록된 파일/페이지 범위야.')
        else:
            default_title=Path(file.name).stem.replace(' 기말고사 퀴즈',' 문제집').replace(' 퀴즈',' 문제집')
            if scanned:default_title+=f' ({page_start}~{page_end}쪽)'
            title=st.text_input('문제집 이름',value=default_title)
            try:
                if not scanned:
                    parsed=extract_pdf(payload)
                else:
                    if not ocr_available():
                        st.error('한국어 OCR 실행 파일이 없어. GitHub에 packages.txt가 올라갔는지 확인해 줘.')
                        parsed=[]
                    else:
                        run_key='ocr_'+fingerprint
                        if st.button('스캔 PDF 인식 시작',type='primary'):
                            bar=st.progress(0,text='한국어 글자를 읽고 있어...')
                            parsed_result=extract_scanned_pdf(payload,int(page_start),int(page_end),
                                progress=lambda n,total:bar.progress(min(n/total,1.0),text=f'{n}/{total}페이지 처리'))
                            st.session_state[run_key]=parsed_result
                            bar.empty()
                        parsed=st.session_state.get(run_key,[])
                if parsed:
                    st.success(f'문제 후보 {len(parsed)}개 인식했어.')
                    if scanned:
                        st.warning('OCR로 인식한 문제는 정확하지 않을 수 있어. 모든 문제·선지와 정답을 원본 PDF와 대조해 줘. OCR 추출 결과는 기본적으로 자동 채점 보류 상태야.')
                    else:
                        st.caption('문제집 등록 전에 정답과 선지를 확인해 줘.')
                    for q in parsed:
                        with st.expander(f'{"⚠️ " if q["needs_review"] else ""}{q["section"]} · {q["number"]}번 · {q["prompt"][:45]}'):
                            if scanned:
                                q['prompt']=st.text_area('문제 문장',value=q['prompt'],key=f'ocrprompt_{fingerprint}_{q["uid"]}')
                                raw=st.text_area('선지 (한 줄에 하나, ①부터 순서대로)',
                                    value='\n'.join(x['label']+' '+x['text'] for x in q['options']),
                                    key=f'ocropts_{fingerprint}_{q["uid"]}')
                                new_options=[]
                                for line in raw.splitlines():
                                    m=re.match(r'^([①②③④⑤⑥⑦⑧⑨⑩])\s*(.*)',line.strip())
                                    if m:new_options.append({'label':m.group(1),'text':m.group(2)})
                                q['options']=new_options
                                q['answer_text']=st.selectbox('원본에서 확인한 정답', ['선택 안 함']+[x['label'] for x in new_options],
                                    key=f'ocranswer_{fingerprint}_{q["uid"]}')
                                if q['answer_text']=='선택 안 함':q['answer_text']=''
                                q['answer_indices']=[i for i,x in enumerate(new_options) if x['label']==q['answer_text']]
                                q['explanation']=st.text_area('해설 (OCR 초안)',value=q['explanation'],
                                    key=f'ocrexplain_{fingerprint}_{q["uid"]}')
                                q['needs_review']=not bool(q['answer_indices']) or len(new_options)<2
                                if q['notes']:st.caption(q['notes'])
                                verified=st.checkbox('문제·선지·정답을 원본과 대조하여 확인함',
                                    key=f'ocrverified_{fingerprint}_{q["uid"]}')
                                q['needs_review']=q['needs_review'] or not verified
                            else:
                                st.write(q['prompt'])
                                for o in q['options']:st.write(o['label']+' '+o['text'])
                                st.write('**정답:** '+(q['answer_text'] or '미기재'))
                                st.write('**해설:** '+(q['explanation'] or '미기재'))
                                if q['notes']:st.warning(q['notes'])
                    valid=[q for q in parsed if len(q['options'])>=2 and len(q['prompt'])>=5]
                    st.caption(f'저장할 수 있는 문제 후보: {len(valid)}/{len(parsed)}개. 정답 미확인 문항은 자동 채점하지 않아.')
                    if st.button('이 문제집 저장',type='primary',disabled=not valid or not title.strip()):
                        api(add_book,title.strip(),file.name,fingerprint,valid)
                        if scanned:st.session_state.pop('ocr_'+fingerprint,None)
                        st.success('문제집을 등록했어!');st.rerun()
                elif not scanned:
                    st.warning('문제를 찾지 못했어. 스캔 PDF (한국어 OCR) 모드로 바꿔서 시도해 봐.')
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
