#!/usr/bin/env bash
# Install this repository's skills from a tag, and record what was installed.
#
#   bash skills/install.sh v6.15.0
#
# Installs kbqa-check and kbqa-merge into ~/.claude/skills/. Run by the
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
# Overrides (for tests only): KBQA_REPO, KBQA_SKILLS_HOME, KBQA_BACKUP_DIR.
set -euo pipefail

TAG="${1:?usage: bash skills/install.sh <tag, e.g. v6.15.0>}"
REPO="${KBQA_REPO:-https://github.com/ramygwprod/kb-qa.git}"
HOME_SKILLS="${KBQA_SKILLS_HOME:-$HOME/.claude/skills}"
BACKUPS="${KBQA_BACKUP_DIR:-$HOME/.kbqa-check-backups}"
SKILLS="kbqa-check kbqa-merge"

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
done

STAMP=$(date -u +%Y%m%dT%H%M%SZ)
for s in ${SKILLS}; do
  DEST="${HOME_SKILLS}/${s}"
  RECORD="INSTALLED-FROM-${s}"
  if [ -e "${DEST}" ]; then
    mkdir -p "${BACKUPS}"
    mv "${DEST}" "${BACKUPS}/${s}-${STAMP}"
    echo "previous ${s} moved to ${BACKUPS}/${s}-${STAMP}"
  fi
  mkdir -p "${DEST}"
  cp -R "${TMP}/src/skills/${s}/." "${DEST}/"
  {
    echo "tag ${TAG}"
    echo "commit ${COMMIT}"
    echo "source ${REPO}"
    echo "installed $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    (cd "${DEST}" && find . -type f ! -name "${RECORD}" | sed 's|^\./||' | sort \
      | while IFS= read -r f; do printf '%s  %s\n' "$(shasum -a 256 "$f" | awk '{print $1}')" "$f"; done)
  } > "${DEST}/${RECORD}"
  echo "installed ${s} ${TAG} (commit ${COMMIT}) into ${DEST} — $(grep -cE '^[0-9a-f]{64}  ' "${DEST}/${RECORD}") files recorded"

  # One copy per skill (PIPELINE-SPEC §5). Other copies are named, not touched.
  for f in "$HOME/Library/Application Support/Claude/local-agent-mode-sessions/skills-plugin/"*/*/skills/"${s}"/SKILL.md; do
    [ -f "$f" ] && echo "ANOTHER COPY: ${f} — remove it, so a session loads only ${DEST}"
  done
done

echo
echo "Next, in this terminal:"
echo "  python3 -m pip install --force-reinstall \"git+${REPO}@${TAG}\""
echo "  bash \"${HOME_SKILLS}/kbqa-check/scripts/preflight.sh\" kbqa-check kbqa-merge"
