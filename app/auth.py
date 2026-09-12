"""Database-backed identity, authorization and browser-session security."""
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException, Request
from sqlalchemy import Boolean, Column, DateTime, Integer, String
from .db import Base, Session, ChatMessage, SessionMemory, Document, KnowledgeBase, _lock_session

TRUSTED_ORIGINS = [x.strip().rstrip('/') for x in os.getenv('TRUSTED_ORIGINS', 'http://localhost:5173,http://127.0.0.1:5173,http://localhost:8000,http://127.0.0.1:8000').split(',') if x.strip()]
COOKIE_NAME = 'rag_session'
COOKIE_SECURE = os.getenv('APP_ENV', 'development').lower() == 'production'
SESSION_HOURS = int(os.getenv('SESSION_HOURS', '12'))
LOGIN_LIMIT = int(os.getenv('LOGIN_MAX_FAILURES', '5'))
LOGIN_WINDOW = int(os.getenv('LOGIN_WINDOW_SECONDS', '900'))

def now(): return datetime.now(timezone.utc).replace(tzinfo=None)

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    username = Column(String(120), unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    is_admin = Column(Boolean, default=False, nullable=False)
    disabled = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=now, nullable=False)

class LoginSession(Base):
    __tablename__ = 'login_sessions'
    token_hash = Column(String(64), primary_key=True)
    user_id = Column(Integer, nullable=False, index=True)
    csrf_token = Column(String(128), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    revoked = Column(Boolean, default=False, nullable=False)

class KBMembership(Base):
    __tablename__ = 'kb_memberships'
    kb_id = Column(Integer, primary_key=True)
    user_id = Column(Integer, primary_key=True)
    role = Column(String(16), nullable=False)

class ConversationOwner(Base):
    __tablename__ = 'conversation_owners'
    session_id = Column(String, primary_key=True)
    user_id = Column(Integer, nullable=False, index=True)
    deleted = Column(Boolean, default=False, nullable=False)

class LoginAttempt(Base):
    __tablename__ = 'login_attempts'
    id = Column(Integer, primary_key=True)
    key = Column(String(64), nullable=False, index=True)
    created_at = Column(DateTime, default=now, nullable=False)


def hash_password(password):
    if not 12 <= len(password) <= 1024:
        raise ValueError('密码必须为 12–1024 个字符')
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return 'scrypt$' + salt.hex() + '$' + digest.hex()

def verify_password(password, encoded):
    try:
        kind, salt, expected = encoded.split('$')
        if kind != 'scrypt' or len(password) > 1024: return False
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
        return hmac.compare_digest(actual.hex(), expected)
    except (ValueError, TypeError): return False

def digest_token(token): return hashlib.sha256(token.encode()).hexdigest()

def check_origin(request):
    if request.headers.get('origin', '').rstrip('/') not in TRUSTED_ORIGINS:
        raise HTTPException(403, '不可信的请求来源')

def current_user(request: Request):
    token = request.cookies.get(COOKIE_NAME, '')
    with Session() as s:
        login = s.get(LoginSession, digest_token(token)) if token else None
        user = s.get(User, login.user_id) if login else None
        if not login or login.revoked or login.expires_at <= now() or not user or user.disabled:
            raise HTTPException(401, '请先登录')
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            check_origin(request)
            if not hmac.compare_digest(request.headers.get('x-csrf-token', ''), login.csrf_token):
                raise HTTPException(403, 'CSRF 校验失败')
        request.state.login_hash = login.token_hash
        request.state.user_id = user.id
        request.state.csrf_token = login.csrf_token
        user._login_hash = login.token_hash
        s.expunge(user)
        return user

def active_user(s, user_id):
    user = s.query(User).filter(User.id == user_id).with_for_update(read=True).first()
    if not user or user.disabled: raise HTTPException(403, '用户已停用')
    return user

def allowed_kb_ids(user_id):
    with Session() as s:
        active_user(s, user_id)
        return [r[0] for r in s.query(KBMembership.kb_id).join(KnowledgeBase, KnowledgeBase.id == KBMembership.kb_id)
                .filter(KBMembership.user_id == user_id)]

def require_kb(user_id, kb_id, role='reader', *, session=None):
    if session is None:
        with Session() as s: return require_kb(user_id,kb_id,role,session=s)
    active_user(session,user_id)
    kb = session.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).with_for_update(read=True).first()
    if not kb: raise HTTPException(404, "知识库不存在或无权访问")
    member = session.query(KBMembership).filter_by(kb_id=kb_id, user_id=user_id).with_for_update(read=True).first()
    levels = {'reader':1,'editor':2,'owner':3}
    if not member or levels.get(member.role,0) < levels[role]:
        raise HTTPException(404, '知识库不存在或无权访问')
    return member

def require_document(user_id, doc_id):
    with Session() as s:
        doc = s.get(Document,doc_id)
        if not doc: raise HTTPException(404, '文档不存在')
        require_kb(user_id,doc.kb_id,session=s)

def require_conversation(user_id, session_id, claim=False, *, session=None):
    if not session_id or len(session_id)>200: raise HTTPException(400,'会话标识无效')
    if session is None:
        with Session() as s:
            require_conversation(user_id,session_id,claim,session=s)
            s.commit()
            return
    active_user(session, user_id)
    _lock_session(session, session_id)
    owner = session.get(ConversationOwner,session_id)
    if owner is None and claim:
        legacy = session.query(ChatMessage.id).filter(ChatMessage.session_id==session_id).first()
        legacy_memory = session.query(SessionMemory.id).filter(SessionMemory.session_id==session_id).first()
        if not legacy and not legacy_memory:
            owner = ConversationOwner(session_id=session_id,user_id=user_id,deleted=False)
            session.add(owner); session.flush()
    if owner is None or owner.deleted or owner.user_id != user_id:
        raise HTTPException(404,'会话不存在或无权访问')

def public_user(user): return {'id':user.id,'username':user.username,'is_admin':user.is_admin,'disabled':user.disabled}

def revoke_user(s,user_id):
    s.query(LoginSession).filter(LoginSession.user_id==user_id).update({'revoked':True})
