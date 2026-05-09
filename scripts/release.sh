#!/usr/bin/env sh
set -eu

usage() {
  cat <<'EOF'
Usage: scripts/release.sh VERSION [--no-push]

Bumps pyproject.toml, creates an annotated vVERSION tag, and pushes the commit
and tag. Pushing the tag triggers .github/workflows/docker-publish.yml to publish
the Docker image to GHCR.

Examples:
  scripts/release.sh 0.2.0
  scripts/release.sh v0.2.0 --no-push
EOF
}

die() {
  printf '%s\n' "$*" >&2
  exit 1
}

version=""
push="true"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --help|-h)
      usage
      exit 0
      ;;
    --no-push)
      push="false"
      ;;
    -*)
      die "Unknown option: $1"
      ;;
    *)
      [ -z "$version" ] || die "Only one VERSION argument is allowed."
      version="$1"
      ;;
  esac
  shift
done

[ -n "$version" ] || {
  usage >&2
  exit 1
}

case "$version" in
  v*) version=${version#v} ;;
esac

printf '%s\n' "$version" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+([-.+][0-9A-Za-z][0-9A-Za-z.-]*)?$' \
  || die "VERSION must look like semver, for example 0.2.0 or v0.2.0."

tag="v$version"
repo_root=$(git rev-parse --show-toplevel)
cd "$repo_root"

[ -f pyproject.toml ] || die "pyproject.toml not found at repository root."

git diff --quiet || die "Working tree has unstaged changes. Commit or stash them before releasing."
git diff --cached --quiet || die "Index has staged changes. Commit or unstage them before releasing."

if git rev-parse -q --verify "refs/tags/$tag" >/dev/null; then
  die "Tag $tag already exists."
fi

current_version=$(sed -n 's/^version = "\(.*\)"$/\1/p' pyproject.toml | head -n 1)
[ -n "$current_version" ] || die "Could not find project version in pyproject.toml."

if [ "$current_version" != "$version" ]; then
  tmp=$(mktemp "${TMPDIR:-/tmp}/printer-release.XXXXXX")
  awk -v version="$version" '
    BEGIN { replaced = 0 }
    /^version = "[^"]+"$/ && !replaced {
      print "version = \"" version "\""
      replaced = 1
      next
    }
    { print }
    END {
      if (!replaced) {
        exit 1
      }
    }
  ' pyproject.toml > "$tmp" || {
    rm -f "$tmp"
    die "Failed to update pyproject.toml."
  }
  mv "$tmp" pyproject.toml

  git diff --check
  git add pyproject.toml
  git commit -m "Release $tag"
else
  printf 'pyproject.toml is already at %s; tagging current commit.\n' "$version"
fi

git tag -a "$tag" -m "Release $tag"

if [ "$push" = "true" ]; then
  git push origin HEAD
  git push origin "$tag"
  printf 'Pushed %s. GitHub Actions will publish ghcr.io/crewday/printer:%s, related semver tags, and latest.\n' "$tag" "$version"
else
  printf 'Created %s locally. Push it with: git push origin HEAD && git push origin %s\n' "$tag" "$tag"
fi
