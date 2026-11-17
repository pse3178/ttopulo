"""Supabase REST API client. Each Streamlit session stores only its own tokens.
All database operations use the signed-in user's JWT. No service role key is used.
Database RLS is the security boundary; UI filters alone are not relied on.
"""
import requests
import streamlit as st

class CloudError(Exception):
    pass


def config():
    try:
        url = str(st.secrets['SUPABASE_URL']).rstrip('/')
        key = str(st.secrets['SUPABASE_ANON_KEY'])
    except Exception as exc:
        raise CloudError('Supabase 연결 설정이 없어. README의 설정 방법을 확인해 줘.') from exc
    if not url.startswith('https://') or not key:
        raise CloudError('Supabase 주소 또는 키를 확인해 줘.')
    return url, key


def call_auth(path, payload=None, method='POST', token=None):
    url, key = config()
    headers = {'apikey': key, 'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    try:
        res = requests.request(method, f'{url}/auth/v1/{path}', headers=headers,
                               json=payload, timeout=25)
    except requests.RequestException as exc:
        raise CloudError('인증 서버에 연결하지 못했어. 인터넷 연결을 확인해 줘.') from exc
    if not res.ok:
        try:
            msg = res.json().get('msg') or res.json().get('error_description') or res.json().get('message')
        except ValueError:
            msg = None
        raise CloudError(msg or f'인증에 실패했어. ({res.status_code})')
    return res.json() if res.content else {}


def save_session(auth):
    st.session_state['auth_access'] = auth['access_token']
    st.session_state['auth_refresh'] = auth['refresh_token']
    user = auth.get('user') or {}
    st.session_state['auth_uid'] = user.get('id')
    st.session_state['auth_email'] = user.get('email')


def login(email, password):
    result = call_auth('token?grant_type=password', {'email': email, 'password': password})
    save_session(result)
    return result


def signup(email, password):
    result = call_auth('signup', {'email': email, 'password': password})
    # Supabase may require email confirmation. Do not log in without a session.
    if result.get('access_token') and result.get('refresh_token'):
        save_session(result)
    return result


def logout():
    token = st.session_state.get('auth_access')
    if token:
        try:
            call_auth('logout', {}, token=token)
        except CloudError:
            pass
    for key in ('auth_access', 'auth_refresh', 'auth_uid', 'auth_email',
                'active_book', 'view', 'current_question'):
        st.session_state.pop(key, None)


def refresh():
    token = st.session_state.get('auth_refresh')
    if not token:
        raise CloudError('로그인 세션이 만료됐어. 다시 로그인해 줘.')
    data = call_auth('token?grant_type=refresh_token', {'refresh_token': token})
    save_session(data)


def db(method, table, params=None, data=None, prefer=None, retry=True):
    url, key = config()
    access = st.session_state.get('auth_access')
    if not access:
        raise CloudError('먼저 로그인해 줘.')
    headers = {'apikey': key, 'Authorization': f'Bearer {access}',
               'Content-Type': 'application/json'}
    if prefer:
        headers['Prefer'] = prefer
    try:
        response = requests.request(method, f'{url}/rest/v1/{table}',
                                    headers=headers, params=params, json=data, timeout=45)
    except requests.RequestException as exc:
        raise CloudError('데이터 서버에 연결하지 못했어.') from exc
    if response.status_code == 401 and retry:
        refresh()
        return db(method, table, params, data, prefer, retry=False)
    if not response.ok:
        try:
            error = response.json().get('message') or response.json().get('hint')
        except ValueError:
            error = None
        raise CloudError(error or f'데이터 저장/조회 오류 ({response.status_code})')
    if not response.content:
        return []
    try:
        return response.json()
    except ValueError:
        return []


def list_books():
    return db('GET','quiz_books',{'select':'id,title,filename,source_hash,created_at',
                                 'order':'created_at.asc'})


def questions(book_id):
    return db('GET','quiz_questions',{'select':'*','book_id':f'eq.{book_id}',
                                     'order':'page.asc,number.asc'})


def progress(book_id):
    return db('GET','quiz_progress',{'select':'question_id,learned,submitted_answer,is_correct,bookmarked',
                                    'book_id':f'eq.{book_id}'})


def add_book(title,filename,source_hash,items):
    uid = st.session_state['auth_uid']
    book = db('POST','quiz_books',data={'owner_id':uid,'title':title,'filename':filename,
                                      'source_hash':source_hash},
              prefer='return=representation')[0]
    rows = []
    for item in items:
        rows.append({
            'owner_id':uid,'book_id':book['id'],'section':str(item.get('section','미분류')),
            'number':int(item.get('number',len(rows)+1)),'page':int(item.get('page',1)),
            'prompt':str(item.get('prompt','')),'options':item.get('options',[]),
            'answer_text':str(item.get('answer_text','')),
            'answer_indices':item.get('answer_indices',[]),
            'explanation':str(item.get('explanation','')),'notes':str(item.get('notes','')),
            'needs_review':bool(item.get('needs_review',False))
        })
    try:
        for i in range(0,len(rows),100):
            db('POST','quiz_questions',data=rows[i:i+100],prefer='return=minimal')
    except Exception:
        db('DELETE','quiz_books',{'id':f'eq.{book["id"]}'})
        raise
    return book['id']


def upsert_progress(book_id,q_id, **fields):
    data={'owner_id':st.session_state['auth_uid'],'book_id':book_id,'question_id':q_id}
    data.update(fields)
    db('POST','quiz_progress',data=data,
       prefer='resolution=merge-duplicates,return=minimal')


def delete_progress(book_id, mode):
    rows=progress(book_id)
    for row in rows:
        if mode == 'learn':
            upsert_progress(book_id,row['question_id'],learned=False)
        else:
            upsert_progress(book_id,row['question_id'],submitted_answer=None,is_correct=None)
