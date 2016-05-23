#!/bin/sh

mkdir -p data
mkdir -p logs/supervisord
mkdir -p logs/sphinxsearch
mkdir -p tmp

docker run -d -p 9012:80 -p 9312:9312 \
    -e DOMAINS="www.maptiler.com,sample" \
    -v `pwd`/data/:/data/ \
    -v `pwd`/logs/supervisord/:/var/log/supervisord/ \
    -v `pwd`/logs/sphinxsearch/:/var/log/sphinxsearch/ \
    -v `pwd`/tmp/:/tmp/ \
    klokantech/search
