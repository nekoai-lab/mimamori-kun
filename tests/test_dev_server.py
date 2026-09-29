"""Run only a copied launcher with synthetic .env and a fake uvicorn."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.parametrize('source', ['inherited', 'dotenv'])
@pytest.mark.parametrize('bad', ['ledger', 'ledger_empty', 'quota', 'quota_empty', 'project_empty', 'cloud_run'])
def test_dev_server_rejects_unsafe_settings(tmp_path, source, bad):
    env = setup(tmp_path)
    patch = {'ledger': {'MIMAMORI_LEDGER':'json'},
             'ledger_empty': {'MIMAMORI_LEDGER':''},
             'quota': {'GOOGLE_CLOUD_QUOTA_PROJECT':'different-fixture'},
             'quota_empty': {'GOOGLE_CLOUD_QUOTA_PROJECT':''},
             'project_empty': {'GOOGLE_CLOUD_PROJECT':''},
             'cloud_run': {'K_SERVICE':'fixture'}}[bad]
    if source == 'inherited':
        env.update(patch)
    else:
        (tmp_path / '.env').write_text('\n'.join(k+'='+v for k,v in patch.items()))
    result = run(tmp_path, env)
    assert result.returncode != 0
    assert ('MIMAMORI_LEDGER' in result.stderr or 'ローカル JSON' in result.stderr or
            'GOOGLE_CLOUD_QUOTA_PROJECT' in result.stderr)
    assert not (tmp_path / 'started').exists()
    assert 'different-fixture' not in result.stdout + result.stderr


def setup(tmp_path):
    (tmp_path / 'scripts').mkdir()
    shutil.copyfile('scripts/dev_server.sh', tmp_path / 'scripts/dev_server.sh')
    (tmp_path / '.venv/bin').mkdir(parents=True)
    stub = tmp_path / '.venv/bin/uvicorn'
    # macOS Bash 3 の [[ ... ]] は set -e だけでは停止しないため明示する。
    stub.write_text('''#!/bin/bash
set -eu
[[ "$GOOGLE_GENAI_USE_VERTEXAI" == TRUE ]] || exit 9
[[ "$GOOGLE_CLOUD_LOCATION" == us-central1 ]] || exit 9
[[ "$MIMAMORI_DEMO" == 1 ]] || exit 9
[[ "$GOOGLE_CLOUD_PROJECT" == "$GOOGLE_CLOUD_QUOTA_PROJECT" ]] || exit 9
[[ ! ${MIMAMORI_LEDGER+x} && ! ${GOOGLE_API_KEY+x} && ! ${GEMINI_API_KEY+x} ]] || exit 9
[[ ! ${MIMAMORI_NOTIFY_WEBHOOK+x} && ! ${MIMAMORI_CALENDAR_ID+x} ]] || exit 9
[[ "$*" == 'main:app --reload --host 127.0.0.1 --port 8080' ]] || exit 9
touch started
''')
    stub.chmod(0o755)
    return dict(PATH=os.defpath, GOOGLE_CLOUD_PROJECT=tmp_path.name, GOOGLE_CLOUD_QUOTA_PROJECT=tmp_path.name)


def run(tmp_path, env):
    return subprocess.run(['bash', 'scripts/dev_server.sh'], cwd=tmp_path, env=env, text=True, capture_output=True)


@pytest.mark.parametrize('source', ['inherited', 'dotenv'])
def test_dev_server_forces_vertex_local_demo_without_external_writes(tmp_path, source):
    env = setup(tmp_path)
    patch = {key:'synthetic-fixture' for key in (
        'GOOGLE_API_KEY', 'GEMINI_API_KEY', 'MIMAMORI_NOTIFY_WEBHOOK', 'MIMAMORI_CALENDAR_ID',
        'GOOGLE_GENAI_USE_VERTEXAI', 'GOOGLE_CLOUD_LOCATION', 'MIMAMORI_DEMO')}
    if source == 'inherited':
        env.update(patch)
    else:
        (tmp_path / '.env').write_text('\n'.join(k+'='+v for k,v in patch.items()))
    result = run(tmp_path, env)
    assert result.returncode == 0
    assert (tmp_path / 'started').exists()
    assert result.stdout == result.stderr == ''
