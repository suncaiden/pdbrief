#!/bin/bash
# Double-click this to start writing.
# It starts PD Brief on your Mac and opens the writing desk in your browser.
# Leave this window open while you write. Close it, or press Control-C, to stop.

cd "$(dirname "$0")" || exit 1

echo ""
echo "  Starting PD Brief..."
echo "  Your browser will open in a moment."
echo ""
echo "  Keep this window open while you write."
echo "  Close it when you are finished."
echo ""

exec python3 build.py --serve --open
