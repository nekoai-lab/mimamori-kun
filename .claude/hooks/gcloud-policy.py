"""Static checks for literal gcloud commands; never execute or print input values."""
import ast
import fnmatch
import json
import os
from pathlib import Path
import re
import shlex
import sys

SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
WRAPPERS = {"env", "command", "sudo", "time", "nohup", "exec", "then", "do", "if", "elif", "!"}
SENSITIVE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:WEBHOOK|SECRET|TOKEN|KEY|PASSWORD)[A-Za-z0-9_]*|(?:WEBHOOK|SECRET|TOKEN|KEY|PASSWORD)[A-Za-z0-9_]*", re.I)
WEBHOOK = re.compile(r"https?://(?:hooks\.slack\.com/[^\s\"\x27]*|(?:canary\.|ptb\.)?discord(?:app)?\.com/api/webhooks/[^\s\"\x27]*|[^\s/\"\x27]*webhook\.office\.com/[^\s\"\x27]*)", re.I)


def commands(source, base=1, depth=0):
    # Preserve physical line numbers while joining backslash continuations.
    has_gcloud = re.search(r"\bgcloud\b", source) is not None
    parts, line_map = [], []
    for n, text in enumerate(source.splitlines(keepends=True), 1):
        if text.rstrip("\r\n").endswith("\\") and not text.lstrip().startswith("#"):
            text = text.rstrip("\r\n")[:-1] + " "
        parts.append(text)
        line_map.extend([base + n - 1] * len(text))
    source = "".join(parts)
    lex = shlex.shlex(source, posix=True, punctuation_chars=";&|()\n")
    lex.whitespace = " \t\r\v"
    lex.whitespace_split = True
    segment = []
    token_line = base
    try:
        while True:
            # shlex counts punctuation newlines again when replaying lookahead.
            # Use the stream offset (minus unread lookahead), never lex.lineno.
            offset = lex.instream.tell() - len(lex._pushback_chars)
            prefix = re.match(r"(?:[ \t\r\v]+|\#[^\n]*(?:\n|$))*", source[offset:])
            offset += prefix.end()
            token_line = line_map[min(offset, len(line_map) - 1)] if line_map else base
            token = lex.get_token()
            if token is None:
                break
            if token and all(c in ";&|()\n" for c in token):
                if segment:
                    yield from inspect_segment(segment, depth)
                segment = []
            else:
                segment.append((token, token_line))
        if segment:
            yield from inspect_segment(segment, depth)
    except ValueError:
        # No input text in diagnostics (it may contain credentials).
        if has_gcloud:
            yield ["__parse_error__"], token_line


def inspect_segment(tokens, depth):
    seg = [token for token, _ in tokens]
    lines = [line for _, line in tokens]
    while seg and (seg[0] in WRAPPERS or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", seg[0])):
        seg = seg[1:]
        lines = lines[1:]
    if not seg:
        return
    line = lines[0]
    name = os.path.basename(seg[0])
    if name == "gcloud":
        yield seg[1:], line
    elif depth < 4 and name in SHELLS:
        for i, arg in enumerate(seg[1:-1], 1):
            if re.fullmatch(r"-[A-Za-z]*c[A-Za-z]*", arg):
                yield from commands(seg[i + 1], lines[i + 1], depth + 1)
                break
    elif depth < 4 and name == "eval":
        yield from commands(" ".join(seg[1:]), line, depth + 1)


def positional(args):
    result = []
    skip = False
    for arg in args:
        if skip:
            skip = False
            continue
        if arg in {"--project", "--configuration", "--account", "--impersonate-service-account", "--verbosity"}:
            skip = True
        elif not arg.startswith("-"):
            result.append(arg)
    return result


def project_reason(args, hook=False):
    if args == ["__parse_error__"]:
        return "コマンドを解析できません。引用符を確認してください"
    pos = positional(args)
    if pos[:3] == ["config", "set", "project"]:
        return "gcloud config set project は禁止です。各コマンドに --project を指定してください"
    if pos[:1] == ["config"]:
        return None
    if hook and (pos[:1] in (["auth"], ["help"], ["version"], ["info"], ["components"], ["topic"]) or "--version" in args or "--help" in args):
        return None
    for i, arg in enumerate(args):
        if arg.startswith("--project=") and arg.split("=", 1)[1]:
            return None
        if arg == "--project" and i + 1 < len(args) and args[i + 1] and not args[i + 1].startswith("-"):
            return None
    # Only a positional operand counts; a flag value is not a project.
    if pos[:1] == ["projects"] and len(pos) >= 3:
        start = args.index(pos[1], args.index("projects") + 1) + 1
        while start < len(args):
            arg = args[start]
            if arg in {"--quiet", "--async"} or (arg.startswith("--") and "=" in arg):
                start += 1
            elif arg.startswith("-"):
                start += 2
            else:
                if arg:
                    return None
                break
    return "gcloud に --project がありません。--project を明示してください"


ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
EXCLUDED = {"tests", "test", ".venv", "venv", "node_modules", ".git", "scripts", ".claude"}
JS_ENV = re.compile(r"\bprocess\s*\.\s*env\s*(?:\.\s*([A-Za-z_][A-Za-z0-9_]*)|\[\s*([\"'])([A-Za-z_][A-Za-z0-9_]*)\2\s*\])")


def environment_reads(root):
    reads = {}
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDED)
        for filename in sorted(files):
            path = Path(directory) / filename
            if path.suffix not in {".py", ".js", ".ts", ".mjs", ".cjs"} or path.is_symlink():
                continue
            source = path.read_text()
            found = []
            if path.suffix == ".py":
                try:
                    tree = ast.parse(source)
                except SyntaxError:
                    # Literal scanning still works for source using a newer Python syntax.
                    pattern = r"\bos\s*\.\s*(?:getenv\s*\(|environ\s*\.\s*get\s*\(|environ\s*\[)\s*([\"'])([A-Za-z_][A-Za-z0-9_]*)\1"
                    found = [(m[2], source.count("\n", 0, m.start()) + 1) for m in re.finditer(pattern, source)]
                else:
                    for node in ast.walk(tree):
                        value = None
                        if isinstance(node, ast.Call) and ast.unparse(node.func) in {"os.getenv", "os.environ.get"} and node.args:
                            value = node.args[0]
                        elif isinstance(node, ast.Subscript) and ast.unparse(node.value) == "os.environ":
                            value = node.slice
                        if isinstance(value, ast.Constant) and isinstance(value.value, str):
                            found.append((value.value, node.lineno))
            else:
                # Remove comments without changing line numbers or quoted strings.
                tokens = r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|//[^\n]*|/\*[\s\S]*?\*/"
                source = re.sub(tokens, lambda m: re.sub(r"[^\n]", " ", m[0]) if m[0].startswith(("//", "/*")) else m[0], source)
                found = [(m[1] or m[3], source.count("\n", 0, m.start()) + 1) for m in JS_ENV.finditer(source)]
            for name, line in found:
                if ENV_NAME.fullmatch(name):
                    reads.setdefault(name, []).append((path.relative_to(root), line))
    return reads


def flag_values(args, flags):
    for i, arg in enumerate(args):
        flag, equal, value = arg.partition("=")
        if flag in flags:
            yield value if equal else (args[i + 1] if i + 1 < len(args) else "")


def secret_names(args):
    names = set()
    for value in flag_values(args, {"--set-secrets", "--update-secrets"}):
        delimiter = ","
        if value.startswith("^"):
            _, delimiter, value = (value.split("^", 2) + [""])[:3]
        if not delimiter:
            continue
        for entry in value.split(delimiter):
            name, equal, reference = entry.partition("=")
            secret, colon, version = reference.rpartition(":")
            if equal and ENV_NAME.fullmatch(name) and secret and colon and version:
                names.add(name)
    return names


def ignore_matches(rule, relative, is_dir):
    """Match a gitignore-style rule, including directory ancestors."""
    pattern = rule[1:] if rule.startswith("!") else rule
    directory_only = pattern.endswith("/")
    anchored = pattern.startswith("/")
    pattern = pattern.strip("/")
    parts = relative.parts

    def match_parts(patterns, names):
        if not patterns:
            return not names
        if patterns[0] == "**":
            return match_parts(patterns[1:], names) or bool(names and match_parts(patterns, names[1:]))
        return bool(names and fnmatch.fnmatchcase(names[0], patterns[0])
                    and match_parts(patterns[1:], names[1:]))

    for end in range(1, len(parts) + 1):
        if directory_only and end == len(parts) and not is_dir:
            continue
        if anchored or "/" in pattern:
            matches = match_parts(pattern.split("/"), parts[:end])
        else:
            matches = fnmatch.fnmatchcase(parts[end - 1], pattern)
        if matches:
            return True
    return False


def upload_included(path, root, rules):
    # Last matching rule wins. An excluded parent cannot be traversed even if
    # a later rule would re-include a child (gitignore/gcloud semantics).
    for candidate in (path, *path.parents):
        if candidate == root:
            break
        included = False
        for _, rule in rules:
            if not rule.startswith("#!") and ignore_matches(
                    rule, candidate.relative_to(root), candidate.is_dir() and not candidate.is_symlink()):
                included = rule.startswith("!")
        if not included:
            return False
    return True


def check(root):
    if not (root / "deploy.sh").is_file():
        print("対象なし: deploy.sh がありません")
        return 0
    errors = []
    def report(path, line, reason):
        errors.append(f"{path}:{line}: {reason}")
    reads = environment_reads(root)
    allowed = set()
    allow_path = root / ".deploy-ready-allow"
    if allow_path.is_file():
        for line, entry in enumerate(allow_path.read_text().splitlines(), 1):
            if not entry.strip() or entry.lstrip().startswith("#"):
                continue
            name, marker, reason = entry.partition("#")
            name = name.strip()
            if not marker or not reason.strip() or not ENV_NAME.fullmatch(name):
                report(".deploy-ready-allow", line, "変数名と # の後に理由が必要です")
                continue
            allowed.add(name)
            if name not in reads:
                print(f".deploy-ready-allow:{line}: 警告: {name} はコードで読まれていません")
    required = {name: locations for name, locations in reads.items() if SENSITIVE.fullmatch(name) and name not in allowed}
    files = [root / "deploy.sh"] + sorted((root / "scripts").glob("*.sh")) + sorted((root / ".github/workflows").glob("*.yml")) + sorted((root / ".github/workflows").glob("*.yaml"))
    for path in files:
        rel = path.relative_to(root)
        source = path.read_text()
        for line, text in enumerate(source.splitlines(), 1):
            if WEBHOOK.search(text):
                report(rel, line, "Webhook URL の直書きは禁止です（URL は非表示）")
        # YAML run block indentation is removed; metadata is ignored. No PyYAML dependency.
        if path.suffix in {".yml", ".yaml"}:
            chunks = []
            lines = source.splitlines()
            i = 0
            while i < len(lines):
                match = re.match(r"^(\s*)(?:-\s*)?run:\s*(.*)$", lines[i])
                if not match:
                    i += 1
                    continue
                indent, value = len(match[1]), match[2]
                start = i + 1
                i += 1
                if value.startswith(("|", ">")):
                    body = []
                    while i < len(lines) and (not lines[i].strip() or len(lines[i]) - len(lines[i].lstrip()) > indent):
                        body.append(lines[i].lstrip())
                        i += 1
                    chunks.append(((" " if value.startswith(">") else "\n").join(body), start + 1))
                else:
                    if value[:1] in ("\"", "\x27") and value[-1:] == value[:1]:
                        value = value[1:-1]
                    chunks.append((value, start))
        else:
            chunks = [(source, 1)]
        for body, base in chunks:
            for args, line in commands(body, base):
                reason = project_reason(args)
                if reason:
                    report(rel, line, reason)
                pos = positional(args)
                if (path == root / "deploy.sh" or path.parent == root / ".github/workflows") and (pos[:2] == ["run", "deploy"] or pos[:3] == ["run", "services", "update"]):
                    supplied = secret_names(args)
                    for name, locations in sorted(required.items()):
                        if name not in supplied:
                            for read_path, read_line in locations:
                                report(rel, line, f"{name} は --set-secrets で渡してください（読んでいる場所：{read_path}:{read_line}）")
                for value in flag_values(args, {"--set-env-vars", "--update-env-vars"}):
                    # gcloud custom delimiters (^:^ etc.) and repeated flags are supported.
                    for name in re.findall(r"([A-Za-z_][A-Za-z0-9_]*)\s*=", value):
                        if SENSITIVE.fullmatch(name) and name not in allowed:
                            report(rel, line, f"{name} は環境変数で渡せません。--set-secrets を使ってください")
    ignore = root / ".gcloudignore"
    if not ignore.is_file():
        report(".gcloudignore", 1, "許可リスト形式の .gcloudignore が必要です")
    else:
        rules = [(n, s.strip()) for n, s in enumerate(ignore.read_text().splitlines(), 1) if s.strip() and (not s.lstrip().startswith("#") or s.lstrip().startswith("#!"))]
        if not rules or rules[0][1] not in {"*", "/*"}:
            report(".gcloudignore", rules[0][0] if rules else 1, "先頭で * または /* により全て除外してください")
        allowed = 0
        banned = [".git", "docs", "samples", "design", "tests", ".env", ".env.local", "scratchpad", "scratchpads", "scratchpad.tmp"]
        for line, rule in rules[1:]:
            if rule.startswith("#!"):
                report(".gcloudignore", line, "#! による外部ルールの読み込みは許可されていません")
                continue
            if not rule.startswith("!"):
                continue
            allowed += 1
            parts = rule[1:].strip("/").split("/")
            # Only explicit paths; directory wildcards may admit private files later.
            invalid = any(c in rule for c in "*?[") or any(
                not part or part in {".", ".."} or part.startswith((".env", "scratchpad"))
                or any(fnmatch.fnmatchcase(name, part) for name in banned)
                for part in parts
            )
            if not invalid:
                target = root.joinpath(*parts)
                children = list(target.rglob("*")) if target.is_dir() and not target.is_symlink() else []
                invalid = target.is_symlink() or any(
                    upload_included(child, root, rules) and (
                        child.is_symlink() or any(part in banned or part.startswith((".env", "scratchpad"))
                                                  for part in child.relative_to(target).parts))
                    for child in children
                )
            if invalid:
                report(".gcloudignore", line, "禁止対象または広すぎるパターンが許可されています。公開するパスを個別に指定してください")
        if not allowed:
            report(".gcloudignore", 1, "! によるアップロード対象の許可が必要です")
    for error in errors:
        print(error)
    return 1 if errors else 0


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--check":
        sys.exit(check(Path(sys.argv[2])))
    try:
        data = json.load(sys.stdin)
    except (ValueError, TypeError):
        sys.exit(0)
    if data.get("tool_name") != "Bash":
        sys.exit(0)
    for arguments, number in commands((data.get("tool_input") or {}).get("command") or ""):
        reason = project_reason(arguments, hook=True)
        if reason:
            print(f"ブロック: {reason}", file=sys.stderr)
            sys.exit(2)
