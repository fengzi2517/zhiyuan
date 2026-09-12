from datetime import timedelta
import secrets
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.exc import IntegrityError
from . import auth
from .db import Session

router = APIRouter()
class LoginRequest(BaseModel):
    username: str = Field(min_length=1,max_length=120)
    password: str = Field(min_length=1,max_length=1024)
    @field_validator('username')
    @classmethod
    def normalized_username(cls, value):
        value = value.strip().lower()
        if not value:
            raise ValueError('用户名不能为空')
        return value
class UserRequest(LoginRequest):
    is_admin: bool = False
class PasswordRequest(BaseModel):
    password: str = Field(min_length=12,max_length=1024)
class MemberRequest(BaseModel):
    user_id: int
    role: str

def admin(user=Depends(auth.current_user)):
    if not user.is_admin: raise HTTPException(403,'需要管理员权限')
    return user

@router.post('/auth/login')
def login(req: LoginRequest, request: Request, response: Response):
    auth.check_origin(request)
    # Account and network limits are independent: changing either cannot bypass the other.
    keys = [auth.digest_token('account:'+req.username.strip().lower()),
            auth.digest_token('ip:'+(request.client.host if request.client else 'unknown'))]
    with Session() as s:
        for key in sorted(keys): auth._lock_session(s,'login:'+key)
        since = auth.now()-timedelta(seconds=auth.LOGIN_WINDOW)
        if any(s.query(auth.LoginAttempt).filter(auth.LoginAttempt.key==key,auth.LoginAttempt.created_at>since).count()>=auth.LOGIN_LIMIT for key in keys):
            raise HTTPException(429,'登录尝试过多，请稍后重试')
        user = s.query(auth.User).filter(auth.User.username==req.username.strip().lower()).with_for_update().first()
        encoded = user.password_hash if user else auth.hash_password('dummy timing password')
        verified = auth.verify_password(req.password,encoded)
        if not user or user.disabled or not verified:
            s.add_all([auth.LoginAttempt(key=key) for key in keys]); s.commit()
            raise HTTPException(401,'用户名或密码错误')
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        s.add(auth.LoginSession(token_hash=auth.digest_token(token),user_id=user.id,csrf_token=csrf,
                               expires_at=auth.now()+timedelta(hours=auth.SESSION_HOURS)))
        s.commit()
        result = {'user':auth.public_user(user),'csrf_token':csrf}
    response.set_cookie(auth.COOKIE_NAME,token,httponly=True,secure=auth.COOKIE_SECURE,
                        samesite='lax',max_age=auth.SESSION_HOURS*3600,path='/')
    return result

@router.get('/auth/me')
def me(request: Request,user=Depends(auth.current_user)):
    return {'user':auth.public_user(user),'csrf_token':request.state.csrf_token}

@router.post('/auth/logout')
def logout(request: Request,response: Response,user=Depends(auth.current_user)):
    with Session() as s:
        s.get(auth.LoginSession,request.state.login_hash).revoked=True; s.commit()
    response.delete_cookie(auth.COOKIE_NAME,path='/',secure=auth.COOKIE_SECURE,httponly=True,samesite='lax')
    return {'ok':True}

@router.get('/admin/users')
def users(user=Depends(admin)):
    with Session() as s: return [auth.public_user(u) for u in s.query(auth.User).order_by(auth.User.id)]

@router.post('/admin/users')
def create_user(req: UserRequest,user=Depends(admin)):
    try: encoded=auth.hash_password(req.password)
    except ValueError as exc: raise HTTPException(400,str(exc))
    with Session() as s:
        item=auth.User(username=req.username.strip().lower(),password_hash=encoded,is_admin=req.is_admin)
        s.add(item)
        try: s.commit()
        except IntegrityError: raise HTTPException(409,'用户名已存在')
        return auth.public_user(item)

@router.post('/admin/users/{user_id}/disable')
def disable_user(user_id:int,user=Depends(admin)):
    if user_id==user.id: raise HTTPException(400,'不能停用当前管理员')
    with Session() as s:
        auth._lock_session(s, 'identity-admin')
        auth.active_user(s, user.id)
        item=s.query(auth.User).filter_by(id=user_id).with_for_update().first()
        if not item: raise HTTPException(404,'用户不存在')
        if item.is_admin and s.query(auth.User).filter_by(is_admin=True, disabled=False).count() <= 1:
            raise HTTPException(409, '不能停用最后一个管理员')
        item.disabled=True; auth.revoke_user(s,user_id); s.commit()
    return {'ok':True}

@router.post('/admin/users/{user_id}/password')
def reset_password(user_id:int,req:PasswordRequest,user=Depends(admin)):
    with Session() as s:
        item=s.query(auth.User).filter_by(id=user_id).with_for_update().first()
        if not item: raise HTTPException(404,'用户不存在')
        item.password_hash=auth.hash_password(req.password); auth.revoke_user(s,user_id); s.commit()
    return {'ok':True}

@router.get('/kbs/{kb_id}/members')
def members(kb_id:int,user=Depends(auth.current_user)):
    auth.require_kb(user.id,kb_id,'owner')
    with Session() as s:
        return [{'user_id':m.user_id,'role':m.role} for m in s.query(auth.KBMembership).filter_by(kb_id=kb_id)]

@router.put('/kbs/{kb_id}/members')
def set_member(kb_id:int,req:MemberRequest,user=Depends(auth.current_user)):
    if req.role not in ('owner','editor','reader'): raise HTTPException(400,'角色无效')
    with Session() as s:
        s.query(auth.KnowledgeBase).filter_by(id=kb_id).with_for_update().first()
        auth.require_kb(user.id,kb_id,'owner',session=s)
        auth.active_user(s,req.user_id)
        if req.user_id==user.id and req.role!='owner': raise HTTPException(400,'不能移除自己的所有者权限')
        s.merge(auth.KBMembership(kb_id=kb_id,user_id=req.user_id,role=req.role)); s.commit()
    return {'ok':True}

@router.delete('/kbs/{kb_id}/members/{user_id}')
def remove_member(kb_id:int,user_id:int,user=Depends(auth.current_user)):
    if user_id==user.id: raise HTTPException(400,'不能移除自己')
    with Session() as s:
        s.query(auth.KnowledgeBase).filter_by(id=kb_id).with_for_update().first()
        auth.require_kb(user.id,kb_id,'owner',session=s)
        s.query(auth.KBMembership).filter_by(kb_id=kb_id,user_id=user_id).delete(); s.commit()
    return {'ok':True}
