#!/bin/sh
# One-time use: git reads password from this script. Token comes from env GITHUB_TOKEN.
# Usage: GITHUB_TOKEN=你的token GIT_ASKPASS=$PWD/git-askpass-voicedemo.sh git push ...
case "$1" in
  *[Uu]sername*) echo "Lyrapower" ;;
  *) echo "${GITHUB_TOKEN}" ;;
esac
