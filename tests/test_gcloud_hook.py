"""gcloud ガード（.claude/hooks/guard-gcloud.sh）の回帰テスト。

フックに PreToolUse の JSON を標準入力で渡し、終了コードだけを見る。gcloud は動かさない。
"""
import json
import subprocess
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parent.parent / ".claude" / "hooks" / "guard-gcloud.sh"


def run_hook(command):
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    return subprocess.run(["bash", str(HOOK)], input=payload, capture_output=True, text=True, timeout=30)


@pytest.mark.parametrize(
    "command",
    [
        # シェルはバックスラッシュ＋改行を空白なしで取り除く（gcl\<改行>oud は gcloud）
        "gcl\\\noud run deploy svc --region asia-northeast1",
        "gcloud config set pro\\\nject p1",
        "gcloud run deploy svc --region asia-northeast1",
    ],
)
def test_blocks_gcloud_without_project_even_when_split_by_line_continuation(command):
    result = run_hook(command)
    assert result.returncode == 2
    assert "ブロック" in result.stderr


@pytest.mark.parametrize(
    "command",
    [
        "ls -la && echo hello",
        "gcl\\\noud run deploy svc --project p1 --region asia-northeast1",
        "gcloud run deploy svc \\\n  --project p1 --region asia-northeast1",
    ],
)
def test_allows_harmless_commands_and_gcloud_with_project(command):
    result = run_hook(command)
    assert result.returncode == 0
    assert result.stderr == ""
