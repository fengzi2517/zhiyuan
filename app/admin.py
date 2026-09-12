"""Explicit identity administration. Run with python -m app.admin --help."""
import argparse
import getpass
from . import auth, db

def password_prompt():
    password=getpass.getpass('Password (at least 12 characters): ')
    if password != getpass.getpass('Confirm password: '): raise ValueError('Passwords do not match')
    return auth.hash_password(password)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    for name in ('bootstrap','create-user','disable-user','reset-password'):
        command=sub.add_parser(name); command.add_argument('username')
        if name=='create-user': command.add_argument('--admin',action='store_true')
    adopt=sub.add_parser('adopt-legacy',help='Explicitly assign unowned legacy data; dry run by default')
    adopt.add_argument('username'); adopt.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    from .migrate import require_schema
    require_schema()
    username=args.username.strip().lower()
    if not username or len(username)>120: parser.error('Invalid username')
    encoded=password_prompt() if args.command in ('bootstrap','create-user','reset-password') else None
    with db.Session.begin() as s:
        db._lock_session(s,'identity-admin')
        user=s.query(auth.User).filter_by(username=username).with_for_update().first()
        if args.command in ('bootstrap','create-user'):
            if user: parser.error('Username already exists')
            if args.command=='bootstrap' and s.query(auth.User).filter_by(is_admin=True).first():
                parser.error('An administrator already exists; use create-user')
            user=auth.User(username=username,password_hash=encoded,is_admin=args.command=='bootstrap' or args.admin)
            s.add(user); s.flush(); print(f'Created user {user.id}: {username}')
        else:
            if not user: parser.error('User not found')
            if args.command=='disable-user':
                if user.is_admin and s.query(auth.User).filter_by(is_admin=True,disabled=False).count()<=1:
                    parser.error('Cannot disable the last active administrator')
                user.disabled=True; auth.revoke_user(s,user.id)
            elif args.command=='reset-password':
                user.password_hash=encoded; auth.revoke_user(s,user.id)
            else:
                report=adopt_legacy(s,user.id,apply=args.apply)
                print(('APPLIED' if args.apply else 'DRY RUN') + ': ' + str(report))

def adopt_legacy(s,user_id,*,apply=False):
    """Operator-only explicit migration; ownership is never inferred at login."""
    if not auth.active_user(s,user_id).is_admin:
        raise ValueError('Legacy adoption requires an active administrator')
    db._lock_session(s,'legacy-adoption')
    kbs=s.query(db.KnowledgeBase).filter(~db.KnowledgeBase.id.in_(s.query(auth.KBMembership.kb_id))).all()
    session_ids={r[0] for r in s.query(db.ChatMessage.session_id).distinct()} | {r[0] for r in s.query(db.SessionMemory.session_id).distinct()}
    owned={r[0] for r in s.query(auth.ConversationOwner.session_id)}
    legacy_sessions=sorted(session_ids-owned)
    null_docs=s.query(db.Document).filter(db.Document.kb_id.is_(None)).count()
    null_chunks=s.query(db.Chunk).filter(db.Chunk.kb_id.is_(None)).count()
    report={'knowledge_bases':len(kbs),'conversations':len(legacy_sessions),'unclassified_documents':null_docs,'unclassified_chunks':null_chunks}
    if apply:
        for kb in kbs: s.add(auth.KBMembership(kb_id=kb.id,user_id=user_id,role='owner'))
        for sid in legacy_sessions:
            db._lock_session(s,sid)
            s.add(auth.ConversationOwner(session_id=sid,user_id=user_id))
        if null_docs or null_chunks:
            # A fresh name prevents accidentally attaching legacy content to an existing shared KB.
            import secrets
            kb=db.KnowledgeBase(name='Legacy import '+secrets.token_hex(6),description='Explicit administrative legacy adoption')
            s.add(kb); s.flush()
            s.add(auth.KBMembership(kb_id=kb.id,user_id=user_id,role='owner'))
            s.query(db.Document).filter(db.Document.kb_id.is_(None)).update({'kb_id':kb.id})
            # Honor the existing document KB when only its chunks lacked an association.
            for chunk in s.query(db.Chunk).filter(db.Chunk.kb_id.is_(None)):
                document=s.get(db.Document,chunk.doc_id)
                chunk.kb_id=document.kb_id if document and document.kb_id is not None else kb.id
    return report

if __name__=='__main__': main()
