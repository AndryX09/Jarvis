#!/usr/bin/env python3
import argparse
import json
import stat
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path


UI_REPO_PATH = "app/dashboard_ui/dashboard.html"
UI_MOUNT_DESTINATION = "/run/jarvis-dashboard-ui"
UI_CONTAINER_PATH = f"{UI_MOUNT_DESTINATION}/dashboard.html"
MAX_UI_BYTES = 256 * 1024
REQUIRED_MARKERS = (
    'data-dashboard="read-only"',
    "/api/dashboard/status",
    'action="/logout"',
)


def validate_branch(actual: str, expected: str) -> None:
    if actual != expected:
        raise ValueError(
            f"branch inatteso: {actual or 'detached HEAD'}; atteso {expected}"
        )


def validate_changed_paths(paths: list[str]) -> None:
    if paths != [UI_REPO_PATH]:
        rendered = ", ".join(paths) if paths else "nessun file"
        raise ValueError(
            "aggiornamento rapido rifiutato: modifiche a "
            f"{rendered}; usa il deploy completo"
        )


def validate_ui_bytes(content: bytes) -> str:
    if len(content) > MAX_UI_BYTES:
        raise ValueError("dashboard UI file is too large")
    try:
        html = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("dashboard UI file must be valid UTF-8") from exc
    for marker in REQUIRED_MARKERS:
        if marker not in html:
            raise ValueError(f"dashboard UI is missing required marker: {marker}")
    return html


def validate_git_object_mode(mode: str) -> None:
    if mode not in {"100644", "100755"}:
        raise ValueError("dashboard UI must be a regular Git file")


def validate_container_inspect(inspect: dict, expected_source: Path) -> None:
    state = inspect.get("State")
    if not isinstance(state, dict) or state.get("Running") is not True:
        raise ValueError("il container pubblico non è in esecuzione")

    mounts = inspect.get("Mounts")
    if not isinstance(mounts, list):
        raise ValueError("ispezione mount Docker non valida")
    matching = [
        mount
        for mount in mounts
        if isinstance(mount, dict)
        and mount.get("Destination") == UI_MOUNT_DESTINATION
    ]
    if len(matching) != 1:
        raise ValueError("il container pubblico non monta la directory UI live")
    mount = matching[0]
    if mount.get("Type") != "bind":
        raise ValueError("la directory UI deve essere un bind mount")
    if mount.get("RW") is not False:
        raise ValueError("il bind mount UI deve essere in sola lettura")
    source = mount.get("Source")
    if not isinstance(source, str) or Path(source).resolve() != expected_source.resolve():
        raise ValueError(f"mount UI inatteso: {source}")

    config = inspect.get("Config")
    environment = config.get("Env") if isinstance(config, dict) else None
    expected_env = f"JARVIS_DASHBOARD_UI_FILE={UI_CONTAINER_PATH}"
    if not isinstance(environment, list) or expected_env not in environment:
        raise ValueError("il container pubblico non usa il file UI live")


def _run(
    command: list[str],
    *,
    cwd: Path,
    binary: bool = False,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        cwd=cwd,
        check=True,
        capture_output=True,
        text=not binary,
    )


def _verify_container_mount(repo_root: Path, container_name: str) -> None:
    raw_inspect = _run(
        [
            "docker",
            "inspect",
            "--format",
            "{{json .}}",
            container_name,
        ],
        cwd=repo_root,
    ).stdout.strip()
    try:
        inspect = json.loads(raw_inspect)
    except json.JSONDecodeError as exc:
        raise ValueError("ispezione Docker non valida") from exc
    if not isinstance(inspect, dict):
        raise ValueError("ispezione Docker non valida")
    validate_container_inspect(inspect, repo_root / "app" / "dashboard_ui")


def _verify_public_login(url: str) -> None:
    with urllib.request.urlopen(url, timeout=10) as response:
        if response.status != 200:
            raise ValueError(f"login pubblico non disponibile: HTTP {response.status}")
        if response.headers.get("Referrer-Policy") != "same-origin":
            raise ValueError("Referrer-Policy pubblica inattesa")


def _merge_with_rollback(
    repo_root: Path,
    target_head: str,
    previous_head: str,
    post_merge_check,
) -> None:
    merged = False
    try:
        _run(["git", "merge", "--ff-only", target_head], cwd=repo_root)
        merged = True
        post_merge_check()
    except Exception:
        if merged:
            try:
                _run(["git", "reset", "--hard", previous_head], cwd=repo_root)
            except Exception as rollback_error:
                raise RuntimeError(
                    "aggiornamento fallito e rollback automatico non riuscito"
                ) from rollback_error
        raise


def _validate_local_ui(repo_root: Path) -> None:
    local_ui = repo_root / UI_REPO_PATH
    local_status = local_ui.lstat()
    if local_ui.is_symlink() or not stat.S_ISREG(local_status.st_mode):
        raise ValueError("dashboard UI locale non è un file regolare")
    with local_ui.open("rb") as handle:
        validate_ui_bytes(handle.read(MAX_UI_BYTES + 1))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Aggiorna solo l'HTML dashboard senza rebuild o restart"
    )
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--branch", default="v1.4.0-http")
    parser.add_argument("--container", default="jarvis-main-http-v1")
    parser.add_argument(
        "--login-url",
        default="https://jarvis.dvdbnc.dpdns.org/login",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    try:
        current_branch = _run(
            ["git", "branch", "--show-current"], cwd=repo_root
        ).stdout.strip()
        validate_branch(current_branch, args.branch)
        status = _run(
            ["git", "status", "--porcelain"], cwd=repo_root
        ).stdout.strip()
        if status:
            raise ValueError("working tree non pulito; commit o annulla le modifiche locali")

        _verify_container_mount(repo_root, args.container)
        _run(
            ["git", "fetch", "--quiet", args.remote, args.branch],
            cwd=repo_root,
        )
        _run(
            ["git", "merge-base", "--is-ancestor", "HEAD", "FETCH_HEAD"],
            cwd=repo_root,
        )
        changed = _run(
            ["git", "diff", "--name-only", "HEAD..FETCH_HEAD"],
            cwd=repo_root,
        ).stdout.splitlines()
        if not changed:
            print("Dashboard UI già aggiornata.")
            return 0
        validate_changed_paths(changed)

        tree_entry = _run(
            ["git", "ls-tree", "FETCH_HEAD", "--", UI_REPO_PATH],
            cwd=repo_root,
        ).stdout.strip()
        fields = tree_entry.split(maxsplit=2)
        if len(fields) != 3 or fields[1] != "blob":
            raise ValueError("dashboard UI Git entry non valida")
        validate_git_object_mode(fields[0])

        remote_ui = _run(
            ["git", "show", f"FETCH_HEAD:{UI_REPO_PATH}"],
            cwd=repo_root,
            binary=True,
        ).stdout
        validate_ui_bytes(remote_ui)
        previous_head = _run(
            ["git", "rev-parse", "HEAD"], cwd=repo_root
        ).stdout.strip()

        def post_merge_check() -> None:
            _validate_local_ui(repo_root)
            _verify_container_mount(repo_root, args.container)
            _verify_public_login(args.login_url)

        _merge_with_rollback(
            repo_root,
            "FETCH_HEAD",
            previous_head,
            post_merge_check,
        )
        commit = _run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=repo_root
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError, ValueError, urllib.error.URLError) as exc:
        print(f"Aggiornamento dashboard non eseguito: {exc}", file=sys.stderr)
        return 1

    print(f"Dashboard UI aggiornata a {commit}; nessun rebuild o restart.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
