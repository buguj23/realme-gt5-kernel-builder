#!/usr/bin/env bash
# Shared multi-mirror and multi-threaded download helpers for domestic CN and global runners.

LIB_MIRROR_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
MIRROR_HELPER="${LIB_MIRROR_DIR}/mirror_helper.py"

resolve_mirror_mode() {
  python3 "$MIRROR_HELPER" mode --mode "${MIRROR_MODE:-auto}"
}

mirror_net_jobs() {
  local cpus
  cpus=$(nproc 2>/dev/null || echo 4)
  local default_jobs=$((cpus * 2))
  [ "$default_jobs" -lt 8 ] && default_jobs=8
  [ "$default_jobs" -gt 24 ] && default_jobs=24
  echo "${NET_JOBS:-$default_jobs}"
}

_is_domestic_url() {
  PYTHONPATH="$LIB_MIRROR_DIR${PYTHONPATH:+:$PYTHONPATH}" python3 -c 'import sys, mirror_helper as m; sys.exit(0 if m.is_domestic_url(sys.argv[1]) else 1)' "$1"
}

git_resilient_args() {
  local url="$1"
  GIT_RESILIENT_ARGS=(
    -c "http.version=HTTP/1.1"
    -c "http.lowSpeedLimit=${GIT_HTTP_LOW_SPEED_LIMIT:-16384}"
    -c "http.lowSpeedTime=${GIT_HTTP_LOW_SPEED_TIME:-45}"
    -c "http.postBuffer=524288000"
  )
  if [ "${MIRROR_FORCE_PROXY:-0}" != 1 ] && _is_domestic_url "$url"; then
    GIT_RESILIENT_ARGS+=(-c "http.proxy=" -c "https.proxy=")
  elif [ "${MIRROR_IGNORE_TUNNEL:-0}" != 1 ] && timeout 1 bash -c '</dev/tcp/127.0.0.1/7890' 2>/dev/null; then
    GIT_RESILIENT_ARGS+=(-c "http.https://github.com.proxy=socks5h://127.0.0.1:7890" -c "https.https://github.com.proxy=socks5h://127.0.0.1:7890")
  fi
}

ensure_repo_url() {
  if [ -z "${REPO_URL:-}" ]; then
    REPO_URL=$(PYTHONPATH="$LIB_MIRROR_DIR" python3 "$MIRROR_HELPER" probe-repo-url --mode "${MIRROR_MODE:-auto}")
    export REPO_URL
  fi
  echo "$REPO_URL"
}

ensure_repo_bin() {
  local dest="${1:-$HOME/.local/bin/repo}"
  if command -v repo >/dev/null 2>&1; then
    command -v repo
    return 0
  fi
  mkdir -p "$(dirname "$dest")"
  PYTHONPATH="$LIB_MIRROR_DIR" python3 "$MIRROR_HELPER" ensure-repo \
    --output "$dest" --mode "${MIRROR_MODE:-auto}" >/dev/null
  export PATH="$(dirname "$dest"):$PATH"
  echo "$dest"
}

download_multi_mirror() {
  local output="$1"
  local expected_sha="${2:-}"
  shift 2
  local jobs
  jobs=$(mirror_net_jobs)
  local args=(--output "$output" --jobs "$jobs" --mode "${MIRROR_MODE:-auto}")
  if [ -n "$expected_sha" ]; then
    args+=(--sha256 "$expected_sha")
  fi
  PYTHONPATH="$LIB_MIRROR_DIR" python3 "$MIRROR_HELPER" download "${args[@]}" "$@"
}

git_clone_resilient() {
  local canonical_url="$1"
  local dest="$2"
  shift 2
  local extra_args=("$@")
  local retries="${MIRROR_RETRIES:-3}"

  local -a candidates
  if [[ "$canonical_url" == https://github.com/* ]] || [[ "$canonical_url" == *"/https://github.com/"* ]]; then
    mapfile -t candidates < <(PYTHONPATH="$LIB_MIRROR_DIR" python3 "$MIRROR_HELPER" probe-github --url "$canonical_url" --mode "${MIRROR_MODE:-auto}")
  else
    candidates=("$canonical_url")
  fi
  [ "${#candidates[@]}" -gt 0 ] || candidates=("$canonical_url")

  local attempt url
  for ((attempt = 1; attempt <= retries; attempt++)); do
    for url in "${candidates[@]}"; do
      if [ -e "$dest" ] && [ ! -e "$dest/.git/HEAD" ]; then
        rm -rf "$dest"
      fi
      [ -e "$dest/.git/HEAD" ] && return 0
      echo "[git-clone attempt $attempt/$retries] $url -> $dest"
      git_resilient_args "$url"
      if GIT_TERMINAL_PROMPT=0 git "${GIT_RESILIENT_ARGS[@]}" clone "${extra_args[@]}" "$url" "$dest"; then
        return 0
      fi
      rm -rf "$dest"
    done
    if [ "$attempt" -lt "$retries" ]; then
      sleep $((attempt * 2))
    fi
  done
  echo "ERROR: git clone failed after $retries rounds for $canonical_url" >&2
  return 1
}

git_fetch_resilient() {
  local repo_dir="$1"
  local canonical_url="$2"
  local ref="$3"
  shift 3
  local extra_args=("$@")
  local retries="${MIRROR_RETRIES:-3}"

  local -a candidates
  if [[ "$canonical_url" == https://github.com/* ]] || [[ "$canonical_url" == *"/https://github.com/"* ]]; then
    mapfile -t candidates < <(PYTHONPATH="$LIB_MIRROR_DIR" python3 "$MIRROR_HELPER" probe-github --url "$canonical_url" --mode "${MIRROR_MODE:-auto}")
  else
    candidates=("$canonical_url")
  fi
  [ "${#candidates[@]}" -gt 0 ] || candidates=("$canonical_url")

  local attempt url
  for ((attempt = 1; attempt <= retries; attempt++)); do
    for url in "${candidates[@]}"; do
      echo "[git-fetch attempt $attempt/$retries] $url ($ref)"
      git_resilient_args "$url"
      if GIT_TERMINAL_PROMPT=0 git -C "$repo_dir" "${GIT_RESILIENT_ARGS[@]}" fetch "${extra_args[@]}" "$url" "$ref"; then
        return 0
      fi
    done
    if [ "$attempt" -lt "$retries" ]; then
      sleep $((attempt * 2))
    fi
  done
  echo "ERROR: git fetch failed after $retries rounds for $canonical_url ($ref)" >&2
  return 1
}

repo_clean_locks() {
  local work_dir="$1"
  [ -d "$work_dir/.repo" ] || return 0
  find "$work_dir/.repo" -maxdepth 5 -type f -name '*.lock' -delete 2>/dev/null || true
}

rewrite_repo_manifests() {
  local work_dir="$1"
  local gh_prefix="$2"
  local aosp_mirror="${3:-}"
  local lineage_mirror="${4:-}"
  local clo_mirror="${5:-}"
  local xml
  local args=()
  [ -n "$aosp_mirror" ] && args+=(--aosp-mirror "$aosp_mirror")
  [ -n "$lineage_mirror" ] && args+=(--lineage-mirror "$lineage_mirror")
  [ -n "$clo_mirror" ] && args+=(--clo-mirror "$clo_mirror")
  args+=(--github-prefix "$gh_prefix")

  while IFS= read -r -d '' xml; do
    python3 "$MIRROR_HELPER" rewrite-manifest --input "$xml" --output "$xml" "${args[@]}"
  done < <(find "$work_dir/.repo" -maxdepth 4 \( -path "$work_dir/.repo/manifest.xml" -o -path "$work_dir/.repo/manifests/*.xml" -o -path "$work_dir/.repo/manifests/*/*.xml" \) -type f -print0 2>/dev/null)
}

_prune_incomplete_repo_projects() {
  local work_dir="$1"
  [ -d "$work_dir/.repo/projects" ] || return 0
  python3 - "$work_dir" <<'PY'
import os
import pathlib
import shutil
import subprocess
import sys

work = pathlib.Path(sys.argv[1]).resolve()
repo_dir = work / ".repo"
projects_dir = repo_dir / "projects"
objects_dir = repo_dir / "project-objects"

# Clean stale temporary packs left behind by interrupted git fetches.
for root_dir in (projects_dir, objects_dir):
    if not root_dir.is_dir():
        continue
    for pack_dir in root_dir.rglob("objects/pack"):
        if not pack_dir.is_dir():
            continue
        for item in pack_dir.iterdir():
            if item.name.startswith("tmp_pack_") or item.name.endswith(".temp"):
                try:
                    if item.is_dir():
                        shutil.rmtree(item, ignore_errors=True)
                    else:
                        item.unlink(missing_ok=True)
                except OSError:
                    pass

def has_any_ref(git_dir: pathlib.Path) -> bool:
    res = subprocess.run(
        ["git", f"--git-dir={git_dir}", "for-each-ref", "--count=1"],
        capture_output=True,
        text=True,
    )
    return res.returncode == 0 and bool(res.stdout.strip())

# Reset projects that created .repo/projects/<path>.git but failed before fetching any ref.
# Otherwise repo/project.py sees (is_new=False and not _HasShallow()) and drops --depth=1.
proj_gits = [p for p in projects_dir.rglob("*.git") if p.is_dir()]
live_obj_dirs = set()
empty_proj = []

for pg in proj_gits:
    obj_link = pg / "objects"
    target_obj_root = None
    if obj_link.exists():
        resolved_obj = pathlib.Path(os.path.realpath(obj_link))
        cand_root = resolved_obj.parent
        try:
            cand_root.relative_to(objects_dir.resolve())
            target_obj_root = cand_root
        except ValueError:
            target_obj_root = None
    if has_any_ref(pg):
        if target_obj_root is not None:
            live_obj_dirs.add(target_obj_root)
    else:
        empty_proj.append((pg, target_obj_root))

pruned = 0
for pg, target_obj_root in empty_proj:
    rel = str(pg.relative_to(projects_dir))[:-4]
    shutil.rmtree(pg, ignore_errors=True)
    wt_git = work / rel / ".git"
    if wt_git.is_symlink() or wt_git.is_file():
        wt_git.unlink(missing_ok=True)
    elif wt_git.is_dir():
        shutil.rmtree(wt_git, ignore_errors=True)
    if (
        target_obj_root is not None
        and target_obj_root not in live_obj_dirs
        and target_obj_root.exists()
        and not has_any_ref(target_obj_root)
    ):
        shutil.rmtree(target_obj_root, ignore_errors=True)
    pruned += 1

if pruned:
    print(f"[repo-sync] pruned {pruned} incomplete/unfetched project(s) to preserve clone-depth", file=sys.stderr)
PY
}

_heal_unborn_repo_worktrees() {
  local work_dir="$1"
  local list_file="$work_dir/.repo/project.list"
  [ -f "$list_file" ] || return 1
  local healed=0 p target
  while IFS= read -r p; do
    [ -n "$p" ] || continue
    [ -e "$work_dir/$p/.git" ] || continue
    if ! git -C "$work_dir/$p" rev-parse --verify -q HEAD >/dev/null 2>&1; then
      target=$(git -C "$work_dir/$p" for-each-ref --format='%(objectname)' --count=1 refs/remotes/m/ 2>/dev/null || true)
      if [ -z "$target" ]; then
        target=$(git -C "$work_dir/$p" rev-parse --verify -q FETCH_HEAD 2>/dev/null || true)
      fi
      if [ -n "$target" ]; then
        echo "[repo-heal] forcing detached checkout for unborn HEAD in $p ($target)" >&2
        if git -C "$work_dir/$p" checkout -f --detach "$target" >/dev/null 2>&1; then
          healed=$((healed + 1))
        fi
      fi
    fi
  done < "$list_file"
  if [ "$healed" -gt 0 ]; then
    echo "[repo-heal] healed $healed unborn worktree(s)" >&2
    return 0
  fi
  return 1
}

repo_sync_resilient() {
  local work_dir="$1"
  local jobs="${2:-$(mirror_net_jobs)}"
  shift 2 || true
  local extra_sync_args=("$@")
  local mode
  mode=$(resolve_mirror_mode)

  local -a gh_prefixes=()
  if [ "$mode" = "cn" ]; then
    if [ -n "${GITHUB_PROXY:-}" ]; then
      gh_prefixes+=("$GITHUB_PROXY")
    fi
    local ranked_url pfx
    while IFS= read -r ranked_url; do
      [ -n "$ranked_url" ] || continue
      if [[ "$ranked_url" == https://github.com/* ]]; then
        pfx="direct"
      else
        pfx="${ranked_url%https://github.com/*}"
      fi
      if [[ " ${gh_prefixes[*]:-} " != *" ${pfx} "* ]]; then
        gh_prefixes+=("$pfx")
      fi
    done < <(PYTHONPATH="$LIB_MIRROR_DIR" python3 "$MIRROR_HELPER" probe-github --url "https://github.com/DestoryG/kernel_manifest.git" --mode "$mode" --timeout 4 2>/dev/null || true)
    for pfx in "https://cdn.gh-proxy.org/" "https://edgeone.gh-proxy.org/" "https://gh-proxy.org/" "https://v6.gh-proxy.org/" "direct"; do
      if [[ " ${gh_prefixes[*]:-} " != *" ${pfx} "* ]]; then
        gh_prefixes+=("$pfx")
      fi
    done
  else
    gh_prefixes=("direct" "https://cdn.gh-proxy.org/" "https://edgeone.gh-proxy.org/" "https://gh-proxy.org/")
  fi

  local aosp_mirror="" lineage_mirror="" clo_mirror="${CLO_MIRROR:-}"
  if [ "$mode" = "cn" ] && [ "${REWRITE_AOSP_MIRROR:-1}" = 1 ]; then
    aosp_mirror=${AOSP_MIRROR:-$(python3 "$MIRROR_HELPER" probe-aosp)}
    lineage_mirror=${LINEAGE_MIRROR:-$(python3 "$MIRROR_HELPER" probe-lineage)}
  fi

  local idx=0 max_attempts="${REPO_SYNC_RETRIES:-4}"
  local prefix
  for ((idx = 0; idx < max_attempts; idx++)); do
    prefix=${gh_prefixes[$((idx % ${#gh_prefixes[@]}))]}
    repo_clean_locks "$work_dir"
    _prune_incomplete_repo_projects "$work_dir"
    if [ "$mode" = "cn" ] || [ -n "$aosp_mirror" ] || [ -n "$lineage_mirror" ] || [ -n "$clo_mirror" ]; then
      rewrite_repo_manifests "$work_dir" "$prefix" "$aosp_mirror" "$lineage_mirror" "$clo_mirror"
    fi
    echo "[repo-sync attempt $((idx + 1))/$max_attempts] jobs=$jobs github_prefix=$prefix"
    if (
      cd "$work_dir"
      export GIT_TERMINAL_PROMPT=0
      export GIT_CONFIG_COUNT=5
      export GIT_CONFIG_KEY_0="http.version"
      export GIT_CONFIG_VALUE_0="HTTP/1.1"
      export GIT_CONFIG_KEY_1="http.postBuffer"
      export GIT_CONFIG_VALUE_1="524288000"
      export GIT_CONFIG_KEY_2="http.lowSpeedLimit"
      export GIT_CONFIG_VALUE_2="${GIT_HTTP_LOW_SPEED_LIMIT:-8192}"
      export GIT_CONFIG_KEY_3="http.lowSpeedTime"
      export GIT_CONFIG_VALUE_3="${GIT_HTTP_LOW_SPEED_TIME:-180}"
      export GIT_CONFIG_KEY_4="protocol.file.allow"
      export GIT_CONFIG_VALUE_4="always"
      repo sync -c -j"$jobs" --no-clone-bundle --no-tags --force-sync "${extra_sync_args[@]}"
    ); then
      return 0
    fi
    if _heal_unborn_repo_worktrees "$work_dir"; then
      if (cd "$work_dir" && GIT_TERMINAL_PROMPT=0 repo sync -l -c -j"$jobs" --no-tags --force-sync); then
        return 0
      fi
    fi
    sleep $(( (idx + 1) * 3 ))
  done
  echo "ERROR: repo sync failed after $max_attempts attempts in $work_dir" >&2
  return 1
}
