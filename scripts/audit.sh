#!/usr/bin/env bash
# The independent audit of a release, run by the operator after installing it.
#
#   bash scripts/audit.sh <tag>          e.g. bash scripts/audit.sh v6.22.0
#
# Clones the tag afresh — never the working copy — and compares it with what
# this machine actually runs: the installed skills, the installed agents, the
# install records, and the kbqa package that the python3 first on PATH imports
# (the interpreter the gates run under, as in the pre-flight). Prints seven
# lines, each OK or DIFF, then one final line:
#
#   1-3  skill kbqa-check / kbqa-merge / kbqa-collect: every installed file is
#        the tag's file, byte for byte, and none is missing or added
#        (the install record and macOS Finder's .DS_Store aside)
#   4    agents: ~/.claude/agents/kbqa-*.md are the tag's agents/kbqa-*.md
#   5    install records: each skill's INSTALLED-FROM record names this tag and
#        the tag's commit
#   6    package version: `python3 -m kbqa --version` is the tag's version
#   7    package code: the installed manifest equals the manifest of the tag's
#        source, computed by the tag's own manifest code, and the tag's
#        pre-flight pins that same manifest
#
# Exits 0 when all seven are OK (AUDIT PASS), 1 on any DIFF (AUDIT FAIL), and 2
# with AUDIT REFUSED when the tag cannot be cloned or the package cannot be
# found — an audit that could not look is not a pass.
#
# It changes nothing: the clone goes to a temporary folder that is removed.
#
# Overrides (for tests only): KBQA_REPO, KBQA_SKILLS_HOME, KBQA_AGENTS_HOME.
set -uo pipefail

TAG="${1:?usage: bash scripts/audit.sh <tag, e.g. v6.22.0>}"
REPO="${KBQA_REPO:-https://github.com/ramygwprod/kb-qa.git}"
SKILLS_HOME="${KBQA_SKILLS_HOME:-$HOME/.claude/skills}"
AGENTS_HOME="${KBQA_AGENTS_HOME:-$HOME/.claude/agents}"
SKILLS="kbqa-check kbqa-merge kbqa-collect"

refuse() { echo "AUDIT REFUSED: $*"; exit 2; }

DIFFS=0
line() {  # line <OK|DIFF> <text>
  [ "$1" = "DIFF" ] && DIFFS=$((DIFFS + 1))
  printf '%-4s %s\n' "$1" "$2"
}

# file listing with sha256, relative to a folder; the record and .DS_Store aside
listing() {
  (cd "$1" && find . -type f ! -name 'INSTALLED-FROM-*' ! -name '.DS_Store' | sed 's|^\./||' | LC_ALL=C sort \
    | while IFS= read -r f; do printf '%s  %s\n' "$(shasum -a 256 "$f" | awk '{print $1}')" "$f"; done)
}

differences() {  # differences <the tag's listing> <the installed listing>: the first five paths that differ
  printf '%s\n' "$1" > "${TMP}/tag.lst"
  printf '%s\n' "$2" > "${TMP}/installed.lst"
  awk 'NR == FNR { if (NF) t[substr($0, 67)] = substr($0, 1, 64); next }
       NF { i[substr($0, 67)] = substr($0, 1, 64) }
       END {
         for (p in t) if (!(p in i)) print "missing: " p; else if (t[p] != i[p]) print "changed: " p
         for (p in i) if (!(p in t)) print "not in the tag: " p
       }' "${TMP}/tag.lst" "${TMP}/installed.lst" \
    | LC_ALL=C sort | head -5 | paste -sd ';' - | sed 's/;/; /g'
}

# The ref must be a tag, as install.sh requires.
git ls-remote --exit-code --tags "${REPO}" "refs/tags/${TAG}" >/dev/null 2>&1 \
  || refuse "${TAG} is not a tag in ${REPO}, or ${REPO} could not be read."
TMP=$(mktemp -d "${TMPDIR:-/tmp}/kbqa-audit.XXXXXX") || refuse "no temporary folder."
trap 'rm -rf "${TMP}"' EXIT
git -c advice.detachedHead=false clone --quiet --depth 1 --branch "${TAG}" "${REPO}" "${TMP}/src" >/dev/null 2>&1 \
  || refuse "could not clone ${REPO} at ${TAG}."
SRC="${TMP}/src"
COMMIT=$(git -C "${SRC}" rev-parse HEAD) || refuse "the clone has no commit."

# The package, as the gates will import it.
command -v python3 >/dev/null 2>&1 || refuse "there is no python3 on PATH."
PY_EXE=$(python3 -c 'import sys; print(sys.executable)' 2>/dev/null)
VERSION=$(python3 -m kbqa --version 2>/dev/null) || refuse "kbqa cannot be imported by ${PY_EXE:-python3}."
KBQA_AT=$(python3 -c 'import os, kbqa; print(os.path.dirname(kbqa.__file__))' 2>/dev/null) \
  || refuse "kbqa cannot be located by ${PY_EXE:-python3}."
INSTALLED_MANIFEST=$(python3 -m kbqa --manifest 2>/dev/null | head -1 | awk '{print $2}')
[ -n "${INSTALLED_MANIFEST}" ] || refuse "kbqa at ${KBQA_AT} prints no manifest."
[ -f "${SRC}/src/kbqa/manifest.py" ] || refuse "${TAG} has no src/kbqa/manifest.py."
TAG_MANIFEST=$(python3 - "${SRC}/src/kbqa/manifest.py" <<'PY' 2>/dev/null
import importlib.util, sys
spec = importlib.util.spec_from_file_location("_kbqa_audit_manifest", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print(mod.MANIFEST_SHA256)
PY
) || refuse "the manifest of ${TAG}'s source could not be computed."
PIN=$(sed -nE 's/^EXPECTED_MANIFEST="\$\{KBQA_EXPECTED_MANIFEST:-([0-9a-f]+)\}"$/\1/p' \
  "${SRC}/skills/kbqa-check/scripts/preflight.sh" 2>/dev/null | head -1)

# 1-3 · the skills
for s in ${SKILLS}; do
  if [ ! -d "${SRC}/skills/${s}" ]; then
    line DIFF "skill ${s}: ${TAG} has no skills/${s}"
  elif [ ! -d "${SKILLS_HOME}/${s}" ]; then
    line DIFF "skill ${s}: not installed at ${SKILLS_HOME}/${s}"
  else
    want=$(listing "${SRC}/skills/${s}")
    have=$(listing "${SKILLS_HOME}/${s}")
    if [ "${want}" = "${have}" ]; then
      line OK "skill ${s}: $(printf '%s\n' "${want}" | grep -c .) files identical to ${TAG}"
    else
      line DIFF "skill ${s}: $(differences "${want}" "${have}")"
    fi
  fi
done

# 4 · the agents
want=$( [ -d "${SRC}/agents" ] && cd "${SRC}/agents" && for f in kbqa-*.md; do
  [ -f "$f" ] && printf '%s  %s\n' "$(shasum -a 256 "$f" | awk '{print $1}')" "$f"; done | LC_ALL=C sort -k2)
have=$( [ -d "${AGENTS_HOME}" ] && cd "${AGENTS_HOME}" && for f in kbqa-*.md; do
  [ -f "$f" ] && printf '%s  %s\n' "$(shasum -a 256 "$f" | awk '{print $1}')" "$f"; done | LC_ALL=C sort -k2)
if [ -z "${want}" ]; then
  line DIFF "agents: ${TAG} has no agents/kbqa-*.md"
elif [ "${want}" = "${have}" ]; then
  line OK "agents: $(printf '%s\n' "${want}" | grep -c .) files in ${AGENTS_HOME} identical to ${TAG}"
else
  line DIFF "agents: $(differences "${want}" "${have}")"
fi

# 5 · the install records
bad=""
for s in ${SKILLS}; do
  record="${SKILLS_HOME}/${s}/INSTALLED-FROM-${s}"
  if [ ! -f "${record}" ]; then
    bad="${bad}${bad:+; }${s}: no record"
    continue
  fi
  rtag=$(awk '$1 == "tag" {print $2; exit}' "${record}")
  rcommit=$(awk '$1 == "commit" {print $2; exit}' "${record}")
  [ "${rtag}" = "${TAG}" ] || bad="${bad}${bad:+; }${s}: tag ${rtag:-none}"
  [ "${rcommit}" = "${COMMIT}" ] || bad="${bad}${bad:+; }${s}: commit ${rcommit:-none}"
done
if [ -z "${bad}" ]; then
  line OK "install records: ${SKILLS// /, } name ${TAG} at ${COMMIT}"
else
  line DIFF "install records: ${bad} (the tag's commit is ${COMMIT})"
fi

# 6 · the package version
if [ "v${VERSION}" = "${TAG}" ]; then
  line OK "package version: kbqa ${VERSION}, imported by ${PY_EXE} from ${KBQA_AT}"
else
  line DIFF "package version: kbqa ${VERSION}, imported by ${PY_EXE} from ${KBQA_AT}; the tag is ${TAG}"
fi

# 7 · the package code
if [ "${INSTALLED_MANIFEST}" = "${TAG_MANIFEST}" ] && [ "${PIN}" = "${TAG_MANIFEST}" ]; then
  line OK "package code: manifest ${INSTALLED_MANIFEST} = ${TAG}'s source = ${TAG}'s pin"
else
  line DIFF "package code: installed ${INSTALLED_MANIFEST}; ${TAG}'s source ${TAG_MANIFEST}; ${TAG}'s pin ${PIN:-none}"
fi

if [ "${DIFFS}" -eq 0 ]; then
  echo "AUDIT PASS: ${TAG} (commit ${COMMIT}) — 7 of 7 OK"
  exit 0
fi
echo "AUDIT FAIL: ${TAG} (commit ${COMMIT}) — ${DIFFS} of 7 DIFF"
exit 1
