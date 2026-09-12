import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app import db, auth

@pytest.fixture
def database(monkeypatch):
    engine = create_engine('sqlite:///:memory:')
    db.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(db, 'Session', factory)
    monkeypatch.setattr(auth, 'Session', factory)
    return factory

def test_password_salted_and_verified():
    a = auth.hash_password('long secure password')
    b = auth.hash_password('long secure password')
    assert a != b
    assert auth.verify_password('long secure password', a)
    assert not auth.verify_password('wrong', a)

def test_membership_and_conversation_isolation(database):
    with database() as s:
        u = auth.User(username='a', password_hash='unused')
        v = auth.User(username='b', password_hash='unused')
        s.add_all([u,v]); s.flush()
        uid, vid = u.id,v.id
        s.add(db.KnowledgeBase(id=1,name='kb'))
        s.add(auth.KBMembership(kb_id=1,user_id=uid,role='reader')); s.commit()
    assert auth.allowed_kb_ids(uid) == [1]
    with pytest.raises(HTTPException): auth.require_kb(uid,1,'editor')
    auth.require_conversation(uid,'new',claim=True)
    with pytest.raises(HTTPException): auth.require_conversation(vid,'new',claim=True)
    db.delete_session('new', user_id=uid)
    with pytest.raises(HTTPException): auth.require_conversation(uid,'new',claim=True)

def test_legacy_conversation_cannot_be_claimed(database):
    with database() as s:
        s.add(auth.User(id=1,username='legacy-user',password_hash='unused'))
        s.add(db.ChatMessage(session_id='legacy',role='user',content='private')); s.commit()
    with pytest.raises(HTTPException): auth.require_conversation(1,'legacy',claim=True)

@pytest.fixture
def client(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy.pool import StaticPool
    from app import auth_routes
    engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    db.Base.metadata.create_all(engine)
    factory=sessionmaker(bind=engine)
    monkeypatch.setattr(db,'Session',factory)
    monkeypatch.setattr(auth,'Session',factory)
    monkeypatch.setattr(auth_routes,'Session',factory)
    with factory() as s:
        s.add(auth.User(username='alice',password_hash=auth.hash_password('password long enough'),is_admin=True)); s.commit()
    app=FastAPI(); app.include_router(auth_routes.router)
    return TestClient(app),factory

def test_browser_session_csrf_revocation(client):
    browser,factory=client
    assert browser.get('/auth/me').status_code==401
    assert browser.post('/auth/login',json={'username':'alice','password':'password long enough'}).status_code==403
    response=browser.post('/auth/login',json={'username':'alice','password':'password long enough'},headers={'origin':auth.TRUSTED_ORIGINS[0]})
    assert response.status_code==200
    assert 'HttpOnly' in response.headers['set-cookie'] and 'SameSite=lax' in response.headers['set-cookie']
    csrf=response.json()['csrf_token']
    assert browser.get('/auth/me').json()['user']['username']=='alice'
    assert browser.post('/auth/logout',headers={'origin':auth.TRUSTED_ORIGINS[0]}).status_code==403
    assert browser.post('/auth/logout',headers={'origin':'https://evil.invalid','x-csrf-token':csrf}).status_code==403
    cookie=browser.cookies.get(auth.COOKIE_NAME)
    with factory() as s:
        assert s.get(auth.LoginSession,auth.digest_token(cookie)) is not None
        assert s.get(auth.LoginSession,cookie) is None
    assert browser.post('/auth/logout',headers={'origin':auth.TRUSTED_ORIGINS[0],'x-csrf-token':csrf}).status_code==200
    browser.cookies.set(auth.COOKIE_NAME,cookie)
    assert browser.get('/auth/me').status_code==401

def test_persistent_login_limit(client):
    browser,factory=client
    for _ in range(auth.LOGIN_LIMIT):
        assert browser.post('/auth/login',json={'username':'alice','password':'wrong'},headers={'origin':auth.TRUSTED_ORIGINS[0]}).status_code==401
    assert browser.post('/auth/login',json={'username':'alice','password':'password long enough'},headers={'origin':auth.TRUSTED_ORIGINS[0]}).status_code==429
    with factory() as s: assert s.query(auth.LoginAttempt).count()==auth.LOGIN_LIMIT*2

def test_scoped_lists_and_completion_revocation(database):
    with database() as s:
        user=auth.User(username='reader',password_hash='unused'); s.add(user); s.flush(); uid=user.id; s.commit()
    kb=db.create_kb('mine',user_id=uid)
    other=db.create_kb('other')
    db.create_document('mine.txt',kb['id']); db.create_document('other.txt',other['id']); db.create_document('legacy.txt')
    assert [x['name'] for x in db.list_kbs(allowed_kb_ids=[kb['id']])]==['mine']
    assert [x['filename'] for x in db.list_documents(allowed_kb_ids=[kb['id']])]==['mine.txt']
    assert db.list_documents(allowed_kb_ids=[])==[]
    auth.require_conversation(uid,'conversation',claim=True)
    with database() as s:
        s.query(auth.KBMembership).delete(); s.commit()
    with pytest.raises(HTTPException):
        db.save_exchange('conversation','question','answer',user_id=uid,allowed_kb_ids=[kb['id']])
    assert db.get_session_messages('conversation')==[]

def test_adopt_legacy_dry_run_and_apply(database):
    from app.admin import adopt_legacy
    with database() as s:
        user=auth.User(username='owner',password_hash='unused',is_admin=True); s.add(user); s.flush(); uid=user.id
        s.add(db.Document(filename='legacy',kb_id=None)); s.add(db.ChatMessage(session_id='old',role='user',content='q')); s.commit()
    with database() as s:
        report=adopt_legacy(s,uid)
        assert report['unclassified_documents']==1
        assert s.query(auth.ConversationOwner).count()==0
    with database() as s: adopt_legacy(s,uid,apply=True); s.commit()
    auth.require_conversation(uid,'old')
    assert len(auth.allowed_kb_ids(uid))==1

def test_expired_login_cannot_complete_exchange(database):
    with database() as s:
        user=auth.User(username='u',password_hash='unused'); s.add(user); s.flush(); uid=user.id
        s.add(auth.LoginSession(token_hash='expired',user_id=uid,csrf_token='c',expires_at=auth.now())); s.commit()
    auth.require_conversation(uid,'pending',claim=True)
    with pytest.raises(HTTPException):
        db.save_exchange('pending','q','a',user_id=uid,login_hash='expired')
    assert db.get_session_messages('pending')==[]
