from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from .. import updates
from ..config import settings
from ..db import audit, get_setting
from ..security import ADMIN_PASSWORD_HASH_KEY, require_auth


def authorized(request: Request):
    if not settings.requires_password and not get_setting(ADMIN_PASSWORD_HASH_KEY, ''):
        raise HTTPException(403, 'Для обновлений необходимо настроить пароль администратора')
    require_auth(request)


router = APIRouter(prefix='/api/updates', tags=['updates'], dependencies=[Depends(authorized)])


class InstallIn(BaseModel):
    tag: str


@router.get('/status')
def status():
    return updates.status()


@router.post('/check')
def check():
    try:
        return {'current_version': updates.current_version(), 'release': updates.check_release(), 'job': updates.read_job()}
    except Exception as exc:
        raise HTTPException(502, 'Не удалось проверить GitHub. Повторите попытку позже.') from exc


@router.post('/install', status_code=202)
def install(body: InstallIn):
    try:
        job = updates.start_update(body.tag)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, 'Не удалось связаться с сервером обновлений') from exc
    audit('panel_update_start', 'version=' + job['target'])
    return job
