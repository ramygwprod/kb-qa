#!/usr/bin/env bash
# Check one subject folder: surfaces, every batch, coverage per surface, mappings.
#
#   check_subject.sh <subject dir> [<project root, default .>]
#
# Run with bash, not zsh: an unmatched glob is fatal in zsh, which reads as
# "the check failed" rather than "nothing to check". Files are found with
# `find`, never with a glob, for the same reason.
#
# Writes nothing itself. kbqa writes `<subject>/_qa/` and `<subject>/_qa-log.jsonl`
# (the log sits in the subject, so the fix-round count is per subject, not per
# working directory).
set -u
D="${1:?usage: check_subject.sh <subject dir> [<project root>]}"
ROOT="${2:-.}"
LOG="$D/_qa-log.jsonl"
STOPS="$D/_stop-conditions.md"
# The mapping references: from the estate's kbqa-estate.json — the file the
# collector reads too, so both sides name the same codebook and element list —
# or, without it, the paths this script has always used.
CODEBOOK="$ROOT/research/standard-work/3-themes/themes-intent-candidate.md"
ELEMENTS="$ROOT/research/standard-work/4-axis2/apqc-v8-elements.jsonl"
CONFIG="$ROOT/kbqa-estate.json"
if [ -f "$CONFIG" ]; then
  _cfg() { python3 -c 'import json,sys; v=json.load(open(sys.argv[1])).get(sys.argv[2]); print(v or "")' "$CONFIG" "$1"; }
  C=$(_cfg themes_codebook) && [ -n "$C" ] && CODEBOOK="$ROOT/$C"
  E=$(_cfg apqc_elements) && [ -n "$E" ] && ELEMENTS="$ROOT/$E"
fi
SURFACE_RE='^(product|docs|help)-([0-9]{4}-[0-9]{2}-[0-9]{2})(-w[0-9]{2})?$'

# One line per verdict: gate, verdict, scanned, finding codes.
HERE="$(cd "$(dirname "$0")" && pwd)"
summ() { python3 "$HERE/summ.py"; }

[ -d "$D" ] || { echo "not a directory: $D"; exit 1; }
echo "# subject: $D"

echo "== surfaces (subject level)"
python3 -m kbqa surfaces --subject "$D" --vendor-dir "$D" --batch _subject-surfaces --log "$LOG" | summ

echo "== batches"
n=0
while IFS= read -r s; do
  [ -n "$s" ] || continue
  n=$((n + 1))
  b=$(basename "$s"); b=${b#_collect-}; b=${b%-staging.md}
  echo "-- $b"
  python3 -m kbqa report --vendor-dir "$D" --batch "$b" --log "$LOG" | sed -n '/status=/,$p' | sed 's/^/  /'
  if [ -f "$D/_map-$b-A.jsonl" ] || [ -f "$D/_map-$b-B.jsonl" ]; then
    MAPS=()
    for L in A B; do [ -f "$D/_map-$b-$L.jsonl" ] && MAPS+=(--map "$D/_map-$b-$L.jsonl"); done
    python3 -m kbqa mapcheck --staging "$s" ${MAPS[@]+"${MAPS[@]}"} --codebook "$CODEBOOK" --elements "$ELEMENTS" \
      --subject "$D" --vendor-dir "$D" --batch "$b" --log "$LOG" | summ
    [ ${#MAPS[@]} -lt 4 ] && echo "   mapping: only one mapper file — agreement not measured"
  fi
done < <(find "$D" -maxdepth 1 -name '_collect-*-staging.md' | sort)
if [ "$n" -eq 0 ]; then
  echo "   ZERO batches found — NOT CHECKED. This is not a clean subject."
fi

echo "== coverage and windows, per surface"
# Arrays, never word-split strings: subject paths contain spaces.
# `${A[@]+"${A[@]}"}` because macOS bash 3.2 with `set -u` treats an empty
# array as unbound.
SARG=(); [ -f "$STOPS" ] && SARG=(--stops "$STOPS")
for surf in product docs help; do
  ROWS=()
  while IFS= read -r f; do
    b=$(basename "$f"); b=${b#_collect-}; b=${b%-staging.md}
    echo "$b" | grep -Eq "$SURFACE_RE" && ROWS+=("$f")
  done < <(find "$D" -maxdepth 1 -name "_collect-$surf-*-staging.md" | sort)
  [ ${#ROWS[@]} -gt 0 ] || { echo "-- $surf: no batch"; continue; }
  # The current denominator: the latest by date, then by correction letter
  # (`…-17.md` before `…-17b.md`). Byte order, so no locale reorders them.
  DEN=$(find "$D" -maxdepth 1 -name "_denominator-$surf-*.md" | LC_ALL=C sort | tail -1)
  echo "-- $surf (${#ROWS[@]} batch(es))"
  if [ -n "$DEN" ]; then
    python3 -m kbqa g4 --denominator "$DEN" --rows "${ROWS[@]}" ${SARG[@]+"${SARG[@]}"} \
      --vendor-dir "$D" --batch "_surface-$surf-coverage" --log "$LOG" | summ
  else
    echo "   NOTE: no _denominator-$surf-<date>.md — coverage of this surface NOT measured"
  fi
  python3 -m kbqa g4 --rows "${ROWS[@]}" ${SARG[@]+"${SARG[@]}"} \
    --vendor-dir "$D" --batch "_surface-$surf-windows" --log "$LOG" | summ
  # Advisory: always exit 0. A repeated term is a question for the operator.
  python3 -m kbqa g5 --rows "${ROWS[@]}" \
    --vendor-dir "$D" --batch "_surface-$surf-bundles" --log "$LOG" | summ
done

LEGACY=()
while IFS= read -r f; do
  b=$(basename "$f"); b=${b#_collect-}; b=${b%-staging.md}
  echo "$b" | grep -Eq "$SURFACE_RE" || LEGACY+=("$f")
done < <(find "$D" -maxdepth 1 -name '_collect-*-staging.md' | sort)
if [ ${#LEGACY[@]} -gt 0 ]; then
  echo "-- legacy batches (${#LEGACY[@]}; name has no surface)"
  LDEN=$(find "$D" -maxdepth 1 -name '_denominator*.md' | grep -Ev '/_denominator-(product|docs|help)-[0-9]' | sort | head -1)
  if [ -n "$LDEN" ]; then
    python3 -m kbqa g4 --denominator "$LDEN" --rows "${LEGACY[@]}" ${SARG[@]+"${SARG[@]}"} | summ
  else
    echo "   NOTE: no denominator — legacy coverage NOT measured"
  fi
fi
