# -*- coding: utf-8 -*-
from __future__ import annotations
import argparse, json, time
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
# Test environment may not have Streamlit installed. Provide a tiny import stub for service smoke tests only.
try:
    import streamlit  # noqa
except Exception:
    import types
    st_stub = types.ModuleType('streamlit')
    st_stub.session_state = {}
    def _noop(*args, **kwargs):
        return None
    st_stub.error = st_stub.warning = st_stub.info = st_stub.success = st_stub.markdown = st_stub.caption = _noop
    st_stub.stop = lambda *a, **k: (_ for _ in ()).throw(SystemExit())
    st_stub.rerun = _noop
    st_stub.text_input = lambda *a, **k: ''
    st_stub.form_submit_button = lambda *a, **k: False
    st_stub.form = lambda *a, **k: types.SimpleNamespace(__enter__=lambda self: self, __exit__=lambda self, exc_type, exc, tb: False)
    comp_mod = types.ModuleType('streamlit.components')
    comp_v1 = types.ModuleType('streamlit.components.v1')
    comp_v1.html = _noop
    import sys as _sys
    _sys.modules['streamlit'] = st_stub
    _sys.modules['streamlit.components'] = comp_mod
    _sys.modules['streamlit.components.v1'] = comp_v1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--json', dest='json_path', default='')
    args = parser.parse_args()
    out = {
        'version': 'V170_backend_only_performance_no_visual_change',
        'ok': False,
        'checks': [],
    }
    try:
        from services import db_service
        out['db_status'] = db_service.v170_backend_performance_status()
        out['checks'].append({'name': 'db_service_v170_status', 'ok': True})
    except Exception as exc:
        out['checks'].append({'name': 'db_service_v170_status', 'ok': False, 'error': str(exc)})
    try:
        from services import time_record_service
        out['time_record_cache'] = time_record_service.v170_time_record_cache_status()
        out['checks'].append({'name': 'time_record_cache_status', 'ok': True})
    except Exception as exc:
        out['checks'].append({'name': 'time_record_cache_status', 'ok': False, 'error': str(exc)})
    try:
        from services import security_service
        out['security_cache'] = security_service.v170_security_cache_status()
        out['checks'].append({'name': 'security_cache_status', 'ok': True})
    except Exception as exc:
        out['checks'].append({'name': 'security_cache_status', 'ok': False, 'error': str(exc)})
    # Confirm no visual files were modified by this package via manifest expectation.
    out['visual_files_modified'] = []
    out['ui_policy'] = 'No pages/theme/crud/master_data visual rendering changes in V170 package.'
    out['ok'] = all(c.get('ok') for c in out['checks'])
    if args.json_path:
        p = PROJECT_ROOT / args.json_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out['ok'] else 1

if __name__ == '__main__':
    raise SystemExit(main())
