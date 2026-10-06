#!/bin/sh
# Builds dist/ for the Cloudflare Worker (backend/wrangler.toml): site/ without the book pictures,
# which go to the R2 bucket el-kitep-books instead (the free plan allows 20,000 asset files).
# Usage: tools/build_cloudflare.sh [version]   (version: appended to app.js/style.css so browsers fetch new copies)
set -e
cd "$(dirname "$0")/.."
rm -rf dist && mkdir dist
tar -C site --exclude='./books/*/img' -cf - . | tar -C dist -xf -
cp backend/_headers dist/_headers   # security headers for the static assets (Cloudflare reads it, never serves it)
if [ -n "$1" ]; then
  sed -i -E "s/(app\.js|style\.css)\"/\1?v=$1\"/" dist/index.html
fi
echo "dist: $(find dist -type f | wc -l) files, $(du -sh dist | cut -f1); pictures: $(find site/books -path '*/img/*' -type f | wc -l)"
