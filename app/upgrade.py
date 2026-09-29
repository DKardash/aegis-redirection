"""Non-networking database migration; invoked against a copy before activation."""
import argparse
import ipaddress
import json
import subprocess
from pathlib import Path

from . import crud, db, l2tp, profiles, xray


def legacy_profile(server_id):
    status = l2tp.read_status()
    users = status.get('users', [])
    if not users:
        raise ValueError('Legacy migration: no L2TP users; manual migration required')
    rows = json.loads(subprocess.check_output(['ip', '-j', '-4', 'address', 'show'], text=True))
    listen = status['interface']['listen_addr']
    if not listen or listen == '0.0.0.0':
        routes = json.loads(subprocess.check_output(['ip', '-j', 'route', 'get', '1.1.1.1'], text=True))
        listen = routes[0].get('prefsrc') or routes[0].get('src')
    matches = [(r['ifname'], a) for r in rows for a in r.get('addr_info', []) if a.get('local') == listen]
    if len(matches) != 1:
        raise ValueError('Legacy migration: cannot identify the L2TP listening interface')
    iface, addr = matches[0]
    local = status['interface']['local_ip']
    start, end = status['pool']['start'], status['pool']['end']
    for value in (listen, local, start, end):
        ipaddress.IPv4Address(value)
    return {'id': 1, 'name': 'L2TP', 'username': users[0]['username'],
            'local_ip': listen, 'prefix': addr['prefixlen'], 'interface': iface,
            'server_id': server_id, 'backup_server_id': None, 'enabled': True,
            'primary': True, 'tproxy_port': 12346, 'ppp_local_ip': local,
            'pool_start': start, 'pool_end': end}


def migrate():
    db.init_db()
    raw = db.get_setting(profiles.PROFILES_KEY, '[]') or '[]'
    items = json.loads(raw)
    if not isinstance(items, list):
        raise ValueError('Invalid egress_profiles: migration refused')
    if not items:
        active_id = int(db.get_setting(crud.ACTIVE_KEY, '0') or '0')
        active = crud.get_server(active_id) if active_id else None
        if active:
            items = [legacy_profile(active['id'])]
            profiles._save(items)
            print('Migrated legacy active server to a primary L2TP interface')
        else:
            raise ValueError('No interface profiles or active server; configure migration manually before updating')
    for p in items:
        for key in ('id', 'server_id', 'local_ip', 'interface', 'prefix', 'tproxy_port', 'ppp_local_ip', 'pool_start', 'pool_end', 'primary', 'enabled'):
            if key not in p:
                raise ValueError(f'Incomplete interface profile: missing {key}')
        if p['enabled'] and not crud.get_server(p['server_id']):
            raise ValueError('Interface refers to a missing server')
    ok, error = xray.test_config(profiles.build_full_config())
    if not ok:
        raise ValueError('Xray configuration check failed: ' + error)
    print(f'Migration and Xray config OK; interfaces={len(items)}')


if __name__ == '__main__':
    migrate()
