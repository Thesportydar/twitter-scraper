#!/bin/bash
set -e

rm -rf nodejs layer.zip
mkdir -p nodejs

docker run --rm \
  --entrypoint "" \
  -v "$PWD":/var/task \
  public.ecr.aws/lambda/nodejs:22 \
  bash -c "
    cd /var/task &&
    npm install --production &&
    mv node_modules nodejs/
  "

zip -r layer.zip nodejs
