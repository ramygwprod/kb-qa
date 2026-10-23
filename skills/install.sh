#!/usr/bin/env bash
# Install this repository's skills from a tag, and record what was installed.
#
#   bash skills/install.sh v6.22.0
#
# Installs kbqa-check, kbqa-merge and kbqa-collect into ~/.claude/skills/, and
# the collector's three agents into ~/.claude/agents/. Run by the
# operator, in their own terminal (PIPELINE-SPEC §5): installs are never made
# by an agent. It installs from the TAG on GitHub, never from a working copy,
# so what lands in ~/.claude/skills/ is the reviewed, tagged text — and in each
# skill's folder it writes INSTALLED-FROM-<skill>: the tag, the commit, and the
# sha256 of every file installed. The pre-flight compares the installed files
# with that record and STOPs on any difference.
#
# An existing install is not deleted: it is moved to a dated backup folder
# OUTSIDE ~/.claude/skills/, because a copy left inside it would be loaded as a
# second skill of the same name.
#
# It does not install the kbqa package. It prints the pip command for that,
# which the operator runs in the same terminal.
#
# A skill's agents are recorded in that skill's record, as `agents/<file>`: the
# pre-flight checks them where they were installed, and STOPs when the project a
# session runs in defines an agent of the same name (a project agent overrides a
# user one, so the recorded agent would silently not be the one used).
#
# Overrides (for tests only): KBQA_REPO, KBQA_SKILLS_HOME, KBQA_AGENTS_HOME,
# KBQA_BACKUP_DIR.
set -euo pipefail

TAG="${1:?usage: bash skills/install.sh <tag, e.g. v6.22.0>}"
REPO="${KBQA_REPO:-https://github.com/ramygwprod/kb-qa.git}"
HOME_SKILLS="${KBQA_SKILLS_HOME:-$HOME/.claude/skills}"
BACKUPS="${KBQA_BACKUP_DIR:-$HOME/.kbqa-check-backups}"
AGENTS_HOME="${KBQA_AGENTS_HOME:-$HOME/.claude/agents}"
SKILLS="kbqa-check kbqa-merge kbqa-collect"

# The subagents a skill delegates to. They live in the repository's agents/.
agents_of() {
  case "$1" in
    kbqa-collect) echo "kbqa-fetcher.md kbqa-row-writer.md kbqa-mapper.md" ;;
    *) echo "" ;;
  esac
}

stop() { echo "STOP: $*" >&2; exit 1; }

# The ref must be a tag. A branch moves; a tag is the reviewed release.
git ls-remote --exit-code --tags "${REPO}" "refs/tags/${TAG}" >/dev/null 2>&1 \
  || stop "${TAG} is not a tag in ${REPO}. Nothing was installed."

# An explicit template: macOS `mktemp -d` alone ignores $TMPDIR.
TMP=$(mktemp -d "${TMPDIR:-/tmp}/kbqa-install.XXXXXX")
trap 'rm -rf "${TMP}"' EXIT
git -c advice.detachedHead=false clone --quiet --depth 1 --branch "${TAG}" "${REPO}" "${TMP}/src" \
  || stop "could not clone ${REPO} at ${TAG}. Nothing was installed."
COMMIT=$(git -C "${TMP}/src" rev-parse HEAD)

# Every skill must be in the tag before any is installed: never half an install.
for s in ${SKILLS}; do
  [ -f "${TMP}/src/skills/${s}/SKILL.md" ] || stop "${TAG} has no skills/${s}/SKILL.md. Nothing was installed."
  for a in $(agents_of "${s}"); do
    [ -f "${TMP}/src/agents/${a}" ] || stop "${TAG} has no agents/${a}. Nothing was installed."
  done
done

STAMP=$(date -u +%Y%m%dT%H%M%SZ)
for s in ${SKILLS}; do
  DEST="${HOME_SKILLS}/${s}"
  RECORD="INSTALLED-FROM-${s}"
  if [ -e "${DEST}" ]; then
    mkdir -p "${BACKUPS}"
    chmod -R u+w "${DEST}"  # installs are read-only (below); writable only to move aside
    mv "${DEST}" "${BACKUPS}/${s}-${STAMP}"
    echo "previous ${s} moved to ${BACKUPS}/${s}-${STAMP}"
  fi
  mkdir -p "${DEST}"
  cp -R "${TMP}/src/skills/${s}/." "${DEST}/"
  for a in $(agents_of "${s}"); do
    mkdir -p "${AGENTS_HOME}"
    if [ -e "${AGENTS_HOME}/${a}" ]; then
      mkdir -p "${BACKUPS}"
      chmod u+w "${AGENTS_HOME}/${a}"
      mv "${AGENTS_HOME}/${a}" "${BACKUPS}/${a%.md}-${STAMP}.md"
      echo "previous ${a} moved to ${BACKUPS}/${a%.md}-${STAMP}.md"
    fi
    cp "${TMP}/src/agents/${a}" "${AGENTS_HOME}/${a}"
  done
  {
    echo "tag ${TAG}"
    echo "commit ${COMMIT}"
    echo "source ${REPO}"
    echo "installed $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    (cd "${DEST}" && find . -type f ! -name "${RECORD}" | sed 's|^\./||' | sort \
      | while IFS= read -r f; do printf '%s  %s\n' "$(shasum -a 256 "$f" | awk '{print $1}')" "$f"; done)
    for a in $(agents_of "${s}"); do
      printf '%s  agents/%s\n' "$(shasum -a 256 "${AGENTS_HOME}/${a}" | awk '{print $1}')" "${a}"
    done
  } > "${DEST}/${RECORD}"
  # Read-only for every process, sessions' scripts included: a session can use
  # the skill and its agents, not overwrite them. The pre-flight still checks.
  chmod -R a-w "${DEST}"
  for a in $(agents_of "${s}"); do chmod a-w "${AGENTS_HOME}/${a}"; done
  echo "installed ${s} ${TAG} (commit ${COMMIT}) into ${DEST} — $(grep -cE '^[0-9a-f]{64}  ' "${DEST}/${RECORD}") files recorded"

  # One copy per skill (PIPELINE-SPEC §5). Other copies are named, not touched.
  for f in "$HOME/Library/Application Support/Claude/local-agent-mode-sessions/skills-plugin/"*/*/skills/"${s}"/SKILL.md; do
    [ -f "$f" ] && echo "ANOTHER COPY: ${f} — remove it, so a session loads only ${DEST}"
  done
done

echo
echo "Next, in this terminal:"
echo "  python3 -m pip install --force-reinstall \"git+${REPO}@${TAG}\""
echo "  bash \"${HOME_SKILLS}/kbqa-check/scripts/preflight.sh\" kbqa-check kbqa-merge kbqa-collect"
