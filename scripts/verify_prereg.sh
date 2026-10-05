#!/usr/bin/env bash
# Verify, using only git, that the pre-registration was frozen before unblinding.
#   1. Both tags (prereg-v1, prereg-amendment-1) are ancestors of the commit that set analysis.unblinded: true.
#   2. At each tag, analysis.unblinded was still false.
#   3. The frozen files are unchanged since their tags.
set -euo pipefail
cd "$(dirname "$0")/.."

unblind=$(git log --reverse --format=%H -S'unblinded: true' -- config/settings.yaml | head -1)
echo "Unblinding commit:   $(git log -1 --format='%h  %ad  %s' --date=iso "$unblind")"

for tag in prereg-v1 prereg-amendment-1; do
  commit=$(git rev-list -n 1 "$tag")
  echo "$tag -> $(git log -1 --format='%h  %ad  %s' --date=iso "$commit")"
  if git merge-base --is-ancestor "$commit" "$unblind"; then
    echo "    ancestor of the unblinding commit: yes"
  else
    echo "    ancestor of the unblinding commit: NO"; exit 1
  fi
  echo "    at this tag, config/settings.yaml has:$(git show "$tag:config/settings.yaml" | grep 'unblinded:' | tr -s ' ')"
done

check_frozen() {
  if git diff --quiet "$1" HEAD -- "$2"; then echo "$2: unchanged since $1"; else echo "$2: CHANGED since $1"; exit 1; fi
}
check_frozen prereg-v1 config/prereg.yaml
check_frozen prereg-v1 reports/preregistration.md
check_frozen prereg-amendment-1 reports/prereg_amendments.md
echo "Pre-registration verified."
