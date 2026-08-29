#!/usr/bin/env bash
# Build the deployable Cryonav bundle, and optionally publish it as a GitHub release asset.
#
#   scripts/bundle.sh              # build to ~/Desktop/cryonav-bundle.tar.gz
#   scripts/bundle.sh --release    # ...and replace the asset on the v1.0.0 release
#
# WHY A SCRIPT. The tar invocation has four exclusions that matter for correctness and two
# flags that matter for cleanliness, and typing it by hand each time is how the .env nearly
# ended up inside it. It is checked here instead.
#
# The macOS flags are not cosmetic trivia:
#   --no-mac-metadata   stops bsdtar writing AppleDouble resource forks
#   --no-xattrs         stops it writing LIBARCHIVE.xattr.* pax headers, which GNU tar on the
#                       server does not understand and reports once PER FILE. Sixty lines of
#                       "Ignoring unknown extended header keyword" on every deploy trains an
#                       operator to scroll past warnings, which is how a real one gets missed.
#   COPYFILE_DISABLE=1  the older env-var form of --no-mac-metadata; harmless belt-and-braces
#                       for whichever tar is on PATH.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${BUNDLE_OUT:-$HOME/Desktop/cryonav-bundle.tar.gz}"
REPO="mrnetwork0001/Cryonav"
TAG="${RELEASE_TAG:-v1.0.0}"

echo "==> Building the frontend"
npm --prefix "$ROOT/frontend" run build >/dev/null
[ -f "$ROOT/frontend/dist/index.html" ] || { echo "ABORT: frontend build produced no dist/" >&2; exit 1; }

echo "==> Packing"
rm -f "$OUT"
# Built as a string, not an array: macOS ships bash 3.2, where expanding an EMPTY array
# under `set -u` is itself an unbound-variable error, and on a GNU-tar machine the list is
# legitimately empty.
#
# Support is detected by TRYING each flag on a throwaway archive, not by grepping `tar --help`.
# bsdtar accepts both of these and mentions neither in its help output, so the grep approach
# silently produced an empty flag list and shipped 80 xattr headers anyway - a check that
# always passes is worse than no check, because it looks like it worked.
TAR_FLAGS=""
_probe="$(mktemp -d)"; : > "$_probe/probe"
for _flag in --no-mac-metadata --no-xattrs; do
  if tar "$_flag" -cf "$_probe/t.tar" -C "$_probe" probe >/dev/null 2>&1; then
    TAR_FLAGS="$TAR_FLAGS $_flag"
  fi
done
rm -rf "$_probe"

# demo/ is developer tooling: Playwright plus its browser-side bundles, and the screen
# recordings it produces. The repo's own .gitignore already declares both are not source, and
# nothing under backend/, deploy/ or scripts/ references demo/ at runtime. They were 228 of
# the bundle's 362 entries and 72% of its size - 21 MB shipped where 5.8 MB was needed, then
# unpacked onto a production host and chowned recursively.
COPYFILE_DISABLE=1 tar \
  --exclude='.git' \
  --exclude='backend/.venv' \
  --exclude='frontend/node_modules' \
  --exclude='demo/node_modules' \
  --exclude='demo/footage' \
  --exclude='.env' \
  --exclude='__pycache__' \
  --exclude='.pytest_cache' \
  --exclude='*.tsbuildinfo' \
  --exclude='.DS_Store' \
  --exclude='.ngxtest' \
  --exclude='.pftest' \
  $TAR_FLAGS \
  -czf "$OUT" -C "$(dirname "$ROOT")" "$(basename "$ROOT")"

echo "==> Verifying the bundle"
# The xattr headers are the thing this script exists to prevent, so confirm they are gone
# rather than trusting that the flags were applied.
if tar tvzf "$OUT" 2>&1 | grep -q "LIBARCHIVE.xattr"; then
  echo "ABORT: bundle still carries xattr pax headers - GNU tar will warn per file" >&2
  exit 2
fi
# A bundle that ships secrets, or that omits the built frontend a Node-less server cannot
# rebuild, is worse than no bundle. Both are checked rather than assumed.
name="$(basename "$ROOT")"
tar tzf "$OUT" | grep -qx "${name}/.env" && { echo "ABORT: .env is inside the bundle" >&2; exit 2; }
tar tzf "$OUT" | grep -qx "${name}/frontend/dist/index.html" \
  || { echo "ABORT: built frontend missing from the bundle" >&2; exit 2; }
# The secret scan. Three things here were wrong and are worth naming, because each made the
# check pass while proving less than it appeared to.
#
# 1. It was wrapped in `if [ -f .env ]`, so on a machine without a .env the scan was skipped
#    ENTIRELY - and the script still printed "no secrets". A check that cannot run must not
#    report success; it now says loudly that it could not verify.
# 2. `while read < file` drops the final line when the file has no trailing newline, so the
#    last variable in .env was never scanned. Reading via a printf that appends one fixes it.
# 3. It grepped for the literal value only. A credential that got base64-encoded or
#    percent-encoded on its way into a build artifact would sail through. Each value is now
#    searched in those forms too.
if [ ! -f "$ROOT/.env" ]; then
  echo "    WARNING: no .env on this machine - the bundle was NOT scanned for secrets." >&2
  echo "             Build where .env lives, or verify by hand before publishing." >&2
else
  work="$(mktemp -d)"; tar xzf "$OUT" -C "$work"
  scanned=0
  # printf guarantees a trailing newline so the last line is never silently dropped.
  while IFS= read -r line; do
    case "$line" in ''|'#'*) continue ;; esac
    val="${line#*=}"
    val="${val%\"}"; val="${val#\"}"; val="${val%\'}"; val="${val#\'}"
    [ ${#val} -lt 12 ] && continue
    scanned=$((scanned + 1))
    b64=$(printf '%s' "$val" | base64 | tr -d '\n')
    url=$(printf '%s' "$val" | sed 's|/|%2F|g; s|+|%2B|g; s|=|%3D|g')
    for form in "$val" "$b64" "$url"; do
      if grep -rqF -- "$form" "$work" 2>/dev/null; then
        rm -rf "$work"
        echo "ABORT: a secret value from .env appears inside the bundle" >&2
        exit 2
      fi
    done
  done <<EOF
$(cat "$ROOT/.env")
EOF
  rm -rf "$work"
  if [ "$scanned" -eq 0 ]; then
    echo "ABORT: .env exists but yielded no scannable values - refusing to claim 'no secrets'." >&2
    exit 2
  fi
  echo "    scanned $scanned secret value(s) x3 encodings against every file in the bundle"
fi
echo "    frontend built, $(du -h "$OUT" | cut -f1)"

if [ "${1:-}" = "--release" ]; then
  echo "==> Publishing to $REPO release $TAG"
  tmp="$(mktemp -d)/cryonav-bundle.tar.gz"
  cp "$OUT" "$tmp"
  gh release upload "$TAG" "$tmp" --repo "$REPO" --clobber
  gh api "repos/$REPO/releases/tags/$TAG" --jq '.assets[] | "    \(.name)  \(.size/1000000|floor) MB  \(.updated_at)"'
  rm -rf "$(dirname "$tmp")"
fi

echo
echo "==> Done: $OUT"
echo "    Deploy on the VPS with:"
echo "      curl -fsSL https://github.com/$REPO/releases/latest/download/cryonav-bundle.tar.gz -o /tmp/cryonav-bundle.tar.gz"
echo "      tar xzf /tmp/cryonav-bundle.tar.gz -C /tmp && cp -a /tmp/Cryonav/. /opt/cryonav/ && rm -rf /tmp/Cryonav"
echo "      sudo chown -R cryonav:cryonav /opt/cryonav && sudo systemctl restart cryonav-api"
