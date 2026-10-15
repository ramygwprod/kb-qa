#!/usr/bin/env bash
# kbqa-check pre-flight (K9). Prints PASS or STOP and exits 0 / 1.
#
#   preflight.sh [skill ...]      default: kbqa-check
#
# Checks the validator once, then each named skill's install record — the
# merge skill runs it as `preflight.sh kbqa-check kbqa-merge`.
#
# It never installs anything. `pip` is denied in this project's settings, so a
# checker that tries to install either fails or asks for a permission it should
# not get. When the pinned validator is not installed, the OPERATOR installs it
# in their own terminal, and this script prints the exact command.
#
# Every check below runs the `python3` first on PATH. That is the interpreter
# the gates will run under, so it is named on the first line of the output: a
# PASS against one interpreter says nothing about another.
#
# Overrides (for tests and fixtures only): KBQA_PINNED, KBQA_EXPECTED_MANIFEST,
# KBQA_REPO, KBQA_SKILLS_HOME, KBQA_SKILL_COPIES (newline-separated paths; empty =
# skip the copy check).

PINNED="${KBQA_PINNED:-v6.15.1}"
EXPECTED_MANIFEST="${KBQA_EXPECTED_MANIFEST:-a4ccacd72b5bf87849a6859dff6d738c371893fec8f7572167c680059c0367b7}"
REPO="${KBQA_REPO:-https://github.com/ramygwprod/kb-qa.git}"
INSTALL="python3 -m pip install --force-reinstall \"git+${REPO}@${PINNED}\""
SKILLS_HOME="${KBQA_SKILLS_HOME:-$HOME/.claude/skills}"
INSTALLER="bash skills/install.sh ${PINNED} (in the kb-qa repository)"
[ $# -gt 0 ] && SKILLS="$*" || SKILLS="kbqa-check"

stop() {
  echo "STOP: $1"
  [ -n "$2" ] && printf '%s\n' "$2"
  echo "No gate was run. A verdict from unknown gate code is not a verdict."
  exit 1
}

# 0 · which python3 -----------------------------------------------------------
PY_PATH=$(command -v python3) \
  || stop "there is no python3 on PATH." \
          "Operator: put the python3 that kbqa is installed into first on PATH, then re-run."
PY_EXE=$(python3 -c 'import sys; print(sys.executable)' 2>/dev/null)
PY_VER=$(python3 -c 'import platform; print(platform.python_version())' 2>/dev/null)
echo "python3: ${PY_PATH} -> ${PY_EXE} (Python ${PY_VER})"

# 1 · the validator this copy pins ------------------------------------------
VERSION=$(python3 -m kbqa --version 2>/dev/null) \
  || stop "kbqa is not installed for ${PY_EXE}." "Operator, in your own terminal: ${INSTALL}"
KBQA_AT=$(python3 -c 'import os, kbqa; print(os.path.dirname(kbqa.__file__))' 2>/dev/null)
echo "kbqa: v${VERSION} at ${KBQA_AT}"
if [ "v${VERSION}" != "${PINNED}" ]; then
  stop "installed kbqa is v${VERSION}; this skill pins ${PINNED}." \
       "Operator, in your own terminal: ${INSTALL}"
fi
MANIFEST=$(python3 -m kbqa --manifest | head -1 | awk '{print $2}')
if [ "${MANIFEST}" != "${EXPECTED_MANIFEST}" ]; then
  stop "kbqa ${PINNED} is installed but its manifest is ${MANIFEST}, expected ${EXPECTED_MANIFEST}." \
       "Operator: reinstall from the tag (${INSTALL}). If it still differs after a fresh reinstall, the skill's expected manifest is out of date — report both values to RamyGW."
fi

# 2 · each installed skill is the tagged skill (PIPELINE-SPEC §5) ------------
# install.sh records the tag and the sha256 of every file it installed. Any
# file changed, added or removed since then is a difference, and a difference
# stops the check: the rules this session loaded are not the tagged rules.
# `.DS_Store` is the one exception — macOS Finder writes it, and nothing loads it.
check_installed() {
  local name="$1" dir="${SKILLS_HOME}/$1" record_name="INSTALLED-FROM-$1"
  local record="${dir}/${record_name}"
  [ -f "${record}" ] \
    || stop "no install record for ${name} at ${record}." "Operator: install the skills from the tag — ${INSTALLER}."
  local rec_tag
  rec_tag=$(awk '$1 == "tag" {print $2; exit}' "${record}")
  [ "${rec_tag}" = "${PINNED}" ] \
    || stop "the installed ${name} came from ${rec_tag:-an unknown tag}; this pre-flight pins ${PINNED}." \
            "Operator: reinstall the skills — ${INSTALLER}."
  local expected actual
  expected=$(grep -E '^[0-9a-f]{64}  ' "${record}" | sort -k2)
  actual=$(cd "${dir}" && find . -type f ! -name "${record_name}" ! -name '.DS_Store' \
    | sed 's|^\./||' | sort | while IFS= read -r f; do
        printf '%s  %s\n' "$(shasum -a 256 "$f" | awk '{print $1}')" "$f"
      done | sort -k2)
  if [ "${expected}" != "${actual}" ]; then
    stop "the installed ${name} differs from what install.sh recorded for ${PINNED}." \
         "$(diff <(printf '%s\n' "${expected}") <(printf '%s\n' "${actual}") | grep -E '^[<>]' | sed 's/^</  recorded:/; s/^>/  on disk: /')
Operator: reinstall the skills — ${INSTALLER}. Never edit an installed copy."
  fi
}

# 3 · one skill, one text ----------------------------------------------------
# Every copy a session can load must be byte-identical to the canonical one.
check_copies() {
  local name="$1" canon="${SKILLS_HOME}/$1/SKILL.md" copies hashes n f
  if [ -n "${KBQA_SKILL_COPIES+set}" ]; then
    copies="${KBQA_SKILL_COPIES}"
  else
    copies="${canon}"
    for f in "$HOME/Library/Application Support/Claude/local-agent-mode-sessions/skills-plugin/"*/*/skills/"${name}"/SKILL.md; do
      [ -f "$f" ] && copies="${copies}
${f}"
    done
  fi
  [ -n "${copies}" ] || return 0
  hashes=$(printf '%s\n' "${copies}" | while IFS= read -r f; do
    [ -f "$f" ] && printf '%s  %s\n' "$(shasum -a 256 "$f" | awk '{print $1}')" "$f"
  done)
  n=$(printf '%s\n' "${hashes}" | awk 'NF{print $1}' | sort -u | wc -l | tr -d ' ')
  if [ "${n}" -gt 1 ]; then
    stop "the ${name} skill copies differ — a session may load stale rules." \
         "$(printf '%s\n' "${hashes}")
Operator: remove the copies other than ${canon}, then re-run."
  fi
}

for name in ${SKILLS}; do
  check_installed "${name}"
  check_copies "${name}"
done

# 4 · a newer release is a note, never a stop ---------------------------------
LATEST=$(git ls-remote --tags "${REPO}" 2>/dev/null | grep -o 'v[0-9][0-9.]*$' | sort -V | tail -1)
[ -n "${LATEST}" ] && [ "${LATEST}" != "${PINNED}" ] \
  && echo "NOTE: ${LATEST} exists; this skill pins ${PINNED}. Checked against ${PINNED}; tell the operator to refresh the skill."

echo "PASS: python3 ${PY_EXE} (Python ${PY_VER}) · kbqa v${VERSION} · manifest ${MANIFEST} · ${SKILLS// /, } = ${PINNED} as recorded · skill copies identical"
exit 0
