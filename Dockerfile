FROM debian:8

RUN apt-get -qq update && apt-get install -qq -y --no-install-recommends \
    ca-certificates \
    curl \
    gawk \
    libexpat1 \
    libpq5 \
    mysql-client \
    nginx \
    python \
    python-setuptools \
    python-pip \
    python-crypto \
    python-flask \
    python-pil \
    unixodbc \
    uwsgi \
    uwsgi-plugin-python \
&& pip install iso8601

RUN curl -s \
    http://sphinxsearch.com/files/sphinxsearch_2.2.10-release-1~jessie_amd64.deb \
    -o /tmp/sphinxsearch.deb \
&& dpkg -i /tmp/sphinxsearch.deb \
&& rm /tmp/sphinxsearch.deb \
&& easy_install -q flask-cache \
&& pip install -q supervisor \
&& mkdir -p /var/log/sphinxsearch \
&& mkdir -p /var/log/supervisord

COPY conf/sphinx/sphinx.conf /etc/sphinxsearch/
COPY conf/nginx/nginx.conf /etc/nginx/sites-available/default
COPY supervisord.conf /etc/supervisor/supervisord.conf
COPY web /usr/local/src/web
COPY sample.tsv /
COPY sphinx-reindex.sh /

ENV SPHINX_PORT=9312 \
    SEARCH_MAX_COUNT=100 \
    SEARCH_DEFAULT_COUNT=20

EXPOSE 80
CMD ["/usr/local/bin/supervisord", "-c", "/etc/supervisor/supervisord.conf"]
