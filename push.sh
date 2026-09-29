#!/bin/bash
MSG="${1:-update}"
git add .
git commit -m "$MSG"
git push
echo "✅ Pushed: $MSG"
