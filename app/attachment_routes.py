"""All attachment operations require the owner and exact conversation scope."""
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
from . import attachments as a, auth, db
from .file_pipeline import MAX_FILES, MAX_FILE_BYTES, MAX_BATCH_BYTES

router = APIRouter(prefix='/sessions/{session_id}/attachments')


@router.post('', status_code=202)
async def upload(session_id: str, files: list[UploadFile], user=Depends(auth.current_user)):
    data, total = [], 0
    try:
        if not files or len(files) > MAX_FILES:
            raise HTTPException(400, '每次最多上传 5 个附件')
        for file in files:
            content = bytearray()
            while block := await file.read(1024 * 1024):
                content.extend(block)
                total += len(block)
                if len(content) > MAX_FILE_BYTES or total > MAX_BATCH_BYTES:
                    raise HTTPException(413, '单文件最多 20 MB，每次最多 50 MB')
            data.append((file.filename or '', bytes(content)))
        return await run_in_threadpool(a.enqueue, user.id, session_id, data)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        for file in files:
            await file.close()


@router.get('')
def items(session_id: str, user=Depends(auth.current_user)):
    return a.list_items(user.id, session_id)


@router.get('/{ident}/original')
def original(session_id: str, ident: str, preview: bool = False, user=Depends(auth.current_user)):
    with db.Session() as s:
        item = a.require_items(s, user.id, session_id, [ident])[0]
        path = a.path_for(item, image=preview and bool(item.image_path))
        return FileResponse(path, filename=item.filename if not preview else 'preview.jpg',
                            content_disposition_type='inline' if preview else 'attachment')


@router.get('/{ident}/content')
def content(session_id: str, ident: str, user=Depends(auth.current_user)):
    with db.Session() as s:
        item = a.require_items(s, user.id, session_id, [ident])[0]
        chunks = s.query(a.AttachmentChunk).filter_by(attachment_id=ident).order_by(a.AttachmentChunk.id).all()
        return dict(id=ident, filename=item.filename, content=item.content, chunks=[{
            name: getattr(c, name) for name in ('id', 'content', 'page_start', 'page_end', 'section', 'start_char', 'end_char')
        } for c in chunks])


@router.post('/{ident}/retry', status_code=202)
def retry(session_id: str, ident: str, user=Depends(auth.current_user)):
    return a.retry(user.id, session_id, ident)


@router.delete('/{ident}')
def remove(session_id: str, ident: str, user=Depends(auth.current_user)):
    a.remove(user.id, session_id, ident)
    return {'ok': True}


class PromotionRequest(BaseModel):
    kb_id: int


@router.post('/{ident}/save-to-kb', status_code=202)
def promote(session_id: str, ident: str, req: PromotionRequest, user=Depends(auth.current_user)):
    return a.promote(user.id, session_id, ident, req.kb_id)
