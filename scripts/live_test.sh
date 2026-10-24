#!/usr/bin/env bash
# Live test: publishes 4 REAL posts. Needs IG_ACCESS_TOKEN and IG_USER_ID in the env.
set -u
: "${IG_ACCESS_TOKEN:?set IG_ACCESS_TOKEN}" "${IG_USER_ID:?set IG_USER_ID}"
if [ "${CONFIRM_LIVE:-}" != "1" ]; then
  echo "This publishes 3 REAL public posts on account $IG_USER_ID. Re-run with CONFIRM_LIVE=1 to proceed." >&2
  exit 1
fi
IMG1="https://fastly.picsum.photos/id/237/1080/1080.jpg?hmac=Xx_85C-aO0_CFono7NdoLg6NybMyGrW3S2yZuBbdj0Q"
IMG2="https://fastly.picsum.photos/id/1015/1080/1080.jpg?hmac=MamcuXAyNG5Ad0vyqBNFCP-idQOT85aQaKFWwpc6Dm0"
VID="https://samplelib.com/mp4/sample-5s.mp4"
run() { echo "== $1"; shift; uv run instagram-publish publish "$@"; echo "-> exit $?"; }

run "1 reel"       "$VID" -c "test reel"
run "2 carousel"   "$IMG1" "$IMG2" -c "test carousel"
run "3 mixed"      "$IMG1" "$VID" -c "test mixed"
run "4 error"      "https://example.invalid/x.jpg"
