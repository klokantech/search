#!/bin/sh -e

REINDEX=0

# Download search.tsv file from domains
if [ ! "$DOMAINS" = "" ]; then
    list_domain=$(echo $DOMAINS | tr "," "\n")
    for domain in $list_domain
    do
        if [ ! -f /data/$domain/search.tsv ]; then
            echo "Downloading  $domain"
            mkdir -p /data/$domain/
            curl -s http://$domain/search.tsv -o /data/$domain/search.tsv
            REINDEX=1
        fi
    done
fi

# Copy sample file if missing
if [ ! -f data/sample/search.tsv ]; then
    mkdir -p /data/sample/
    cp /sample.tsv data/sample/search.tsv
fi

# Reindex and rotate files
if [ $REINDEX -eq 1 ]; then
    mkdir -p /data/index/
    /usr/bin/indexer -c /etc/sphinxsearch/sphinx.conf --rotate --all
fi

# Start sphinx job in supervisor
if [ -z "`pidof searchd`" ]; then
    supervisorctl -c /etc/supervisor/supervisord.conf start sphinx
fi
