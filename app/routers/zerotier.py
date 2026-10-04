from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import zerotier
from ..db import audit
from ..security import require_auth

router = APIRouter(prefix='/api/zerotier', tags=['zerotier'], dependencies=[Depends(require_auth)])


class NetworkConfig(BaseModel):
    network_id: str
    cidr: str = '10.241.0.0/16'
    source_ip: str = ''


@router.get('/status')
def status():
    return zerotier.status()


@router.post('/config')
def save_config(body: NetworkConfig):
    try:
        result = zerotier.save_config(body.network_id, body.cidr, body.source_ip)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    audit('zerotier_config', 'network_id=' + result['network_id'] + ' cidr=' + result['cidr'] + ' source_ip=' + (result['source_ip'] or 'auto'))
    return result


@router.post('/connect', status_code=202)
def connect():
    try:
        job = zerotier.start_connect()
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    audit('zerotier_connect', 'setup_id=' + job['id'])
    return job


@router.post('/retry', status_code=202)
def retry():
    try:
        job = zerotier.start_connect()
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    audit('zerotier_retry', 'setup_id=' + job['id'])
    return job
