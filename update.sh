#!/bin/bash

python generate_homepage.py  # Replace with the name of your Python script
git config --global user.email "brian@abelson.live"
git config --global user.name "Brian Abelson"
git add public/index.html  # Stage the updated index.html
git commit -m "Update index.html"  # Commit the changes
if [ -n "$(git status --porcelain)" ]; then
    echo "there are changes"
    git push origin $CI_COMMIT_BRANCH # Push the changes to the remote repository
else
    echo "no changes"
fi