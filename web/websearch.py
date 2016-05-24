#!/usr/bin/env python
# -*- coding: utf-8 -*-
# WebSearch gate for SphinxSearch
#
# Copyright (C) 2016 Klokan Technologies GmbH (http://www.klokantech.com/)
#   All Rights Reserved
# Unauthorized copying of this file, via any medium is strictly prohibited
# Proprietary and confidential
# Author: Martin Mikita (martin.mikita @ klokantech.com)
# Date: 19.05.2016

from flask import Flask, request, Response, render_template, url_for
from sphinxapi import *
from pprint import pprint, pformat
from json import dumps
from os import getenv
from subprocess import Popen, PIPE
from urllib import unquote
import requests


app = Flask(__name__, template_folder='templates/')
app.debug = not getenv('WEBSEARCH_DEBUG') is None
app.debug = True

domains = getenv('DOMAINS')
if domains is None or len(domains) < 0:
    raise Exception('Missing required environment variable DOMAINS!')
    sys.exit(1)

# Split domains by comma and prepare source/index for this domain:
# Input data /data/<domain>/search.tsv
domains = domains.split(',')

# Return maximal number of results
SEARCH_MAX_COUNT = 100
SEARCH_DEFAULT_COUNT = 20
if getenv('SEARCH_MAX_COUNT'):
    SEARCH_MAX_COUNT = int(getenv('SEARCH_MAX_COUNT'))
if getenv('SEARCH_DEFAULT_COUNT'):
    SEARCH_DEFAULT_COUNT = int(getenv('SEARCH_DEFAULT_COUNT'))



# ---------------------------------------------------------
"""
Process query to Sphinx searchd
"""
def process_query(index, query, query_filter, start=0, count=0):
    global SEARCH_MAX_COUNT, SEARCH_DEFAULT_COUNT
    # default server configuration
    host = 'localhost'
    port = 9312
    if getenv('WEBSEARCH_SERVER'):
        host = getenv('WEBSEARCH_SERVER')
    if getenv('WEBSEARCH_SERVER_PORT'):
        port = int(getenv('WEBSEARCH_SERVER_PORT'))
    # pprint([host, port, getenv('WEBSEARCH_SERVER')])

    #querylist = query.split(" ")
    #query = "|".join(querylist)

    if count == 0:
        count = SEARCH_DEFAULT_COUNT
    count = min(SEARCH_MAX_COUNT, count)

    repeat = 3
    result = None
    # Repeat 3 times request because of socket.timeout
    while repeat > 0:
        try:
            cl = SphinxClient()
            cl.SetServer (host, port)
            cl.SetConnectTimeout(5.0) # float seconds
            cl.SetLimits(start, count) #offset, limit, maxmatches=0, cutoff=0
            # cl.SetSortMode( SPH_SORT_ATTR_DESC, 'date')
            cl.SetMatchMode(SPH_MATCH_EXTENDED2)
            cl.SetFieldWeights({
                'title': 30,
                'content': 1,
                'tags': 15,
            })

            # Prepare filter for query, except tags
            for f in query_filter:
                if query_filter[f] is None or f == 'tags':
                    continue
                cl.SetFilterString(f, query_filter[f])
            # Tags contains special prefix
            prefix = ''
            if query_filter['tags'] is not None:
                prefix = "@tags {}".format(' | '.join(query_filter['tags'].split(',')))
            query = query.encode('utf-8')
            if prefix:
                if not query.startswith('@'):
                    prefix += ' @* '
            # Process query under index
            pprint(prefix + query)
            result = cl.Query ( prefix + query, index )
            # pprint(result)
            repeat = 0
        except socket.timeout:
            repeat -= 1

    # Debug
    # resx = result.copy()
    # resx['matches'] = len(result['matches'])
    # pprint(resx)

    status = True
    if not result:
        result = {
            'message': cl.GetLastError(),
            'total_found': 0,
            'matches': [],
        }
        status = False

    result['count'] = count
    result['startIndex'] = start
    result['status'] = status
    return status, prepareResultJson(result)



# ---------------------------------------------------------
def prepareResultJson(result):
    from pprint import pprint

    response = {
        'results': [],
        'startIndex': result['startIndex'],
        'count': result['count'],
        'totalResults': result['total_found'],
    }
    for row in result['matches']:
        r = row['attrs']
        res = {'rank': row['weight'], 'id': row['id']}
        for attr in r:
            if isinstance(r[attr], str):
                res[attr] = r[attr].decode('utf-8')
            else:
                res[ attr ] = r[attr]
        response['results'].append(res)

    # Prepare next and previous index
    nextIndex = result['startIndex'] + result['count']
    if nextIndex <= result['total_found']:
        response['nextIndex'] = nextIndex
    prevIndex = result['startIndex'] - result['count']
    if prevIndex >= 0:
        response['previousIndex'] = prevIndex

    return response



# ---------------------------------------------------------
"""
Format response output
"""
def formatResponse(data, code=200):
    # Format json - return empty
    result = data['result'] if 'result' in data else {}
    format = 'json'
    if request.args.get('format'):
        format = request.args.get('format')
    if 'format' in data:
        format = data['format']

    tpl = data['template'] if 'template' in data else 'answer.html'
    if format == 'html' and tpl is not None:
        if 'route' not in data:
            data['route'] = '/'
        return render_template(tpl, rc=True if code == 200 else False, **data), code

    json = dumps( result )
    mime = 'application/json'
    # Append callback for JavaScript
    if request.args.get('callback'):
        json = request.args.get('callback') + "("+json+");";
        mime = 'application/javascript'
    return Response(json, mimetype=mime), code



# ---------------------------------------------------------
"""
Searching for display name
"""
@app.route('/displayName')
def displayName():
    ret = {}
    rc = False
    index = 'ind_name'
    q = request.args.get('q')
    data = {'query': q, 'index': index, 'route': '/displayName', 'template': 'answer.html'}
    rc, result = process_query(ret, index, q)
    if rc and not request.args.get('debug'):
        ret = result
    data['result'] = ret
    return formatResponse(rc, data)



# ---------------------------------------------------------
"""
API Search endpoint
"""
@app.route('/search')
def search():
    global domains
    code = 400

    data = {'query': '', 'route': '/search', 'template': 'answer.html'}

    # /search?domain={domain}&q={q}&type=post&lang=en&date=?????&tags=a,b,c
    domain = request.args.get('domain')
    if domain not in domains:
        data['result'] = {'error': 'Domain not allowed!'}
        return formatResponse(data, 403)
    domain_id = domain.replace('.', '').replace(':', '').replace('/', '')
    data['domain'] = domain

    index = 'search_{}_index'.format(domain_id)
    if request.args.get('index'):
        index = request.args.get('index').encode('utf-8')
    q = request.args.get('q')
    query_filter = {'type': None, 'lang': None, 'date': None, 'tags': None}
    for f in query_filter:
        if request.args.get(f):
            v = request.args.get(f)
            query_filter[f] = v.encode('utf-8')

    pprint(query_filter)

    if not q:
        data['result'] = {'error': 'Missing query!'}
        return formatResponse(data, 404)
    data['query'] = q

    start = 0
    count = 0
    # Default limit 20
    if request.args.get('startIndex'):
        start = int(request.args.get('startIndex'))
    if request.args.get('count'):
        count = int(request.args.get('count'))

    data['url'] = request.url

    rc = False
    rc, result = process_query(index, q, query_filter, start, count)
    if rc:
        code = 200

    data['result'] = result

    # Prepare URLs
    args = dict(request.args)
    if 'startIndex' in args:
        del(args['startIndex'])
    # pprint(request.url)

    data['previous_page_url'] = data['next_page_url'] = '#'
    if 'previousIndex' in result:
        data['previous_page_url'] = url_for('search', startIndex=result['previousIndex'], **args)
    if 'nextIndex' in result:
        data['next_page_url'] = url_for('search', startIndex=result['nextIndex'], **args)

    return formatResponse(data, code)



# ---------------------------------------------------------
"""
API Update endpoint
"""
@app.route('/update/<path:domain>', methods = ['POST'])
def update(domain):
    global domains
    data = {'route': '/update', 'template': None}

    domain = unquote(domain)
    if domain not in domains:
        data['result'] = {'error': 'Domain not allowed!'}
        return formatResponse(data, 403)
    
    domain_id = domain.replace('.', '').replace(':', '').replace('/', '').encode('utf-8')
    data['domain'] = domain.encode('utf-8')
    url = 'http://%(domain)s/search.tsv' % data
    path = '/data/%(domain)s/search.tsv' % data

    try:
        code = 404
        # 1. Download search.tsv from this domain
        r = requests.get(url, stream=True)
        if r.status_code != 200:
            data['result'] = {'error': 'Cannot download search.tsv from the domain {}'.format(domain)}
            return formatResponse(data, code)

        with open(path, 'wb') as f:
            for chunk in r.iter_content(1024):
                f.write(chunk)

        code = 400

        # 2. Reindex and rotate indexes for this domain
        index_data = {
            'column': 'index',
            'domain_id': domain_id,
        }
        indexes = [
            'ind_%(domain_id)s_%(column)s',
            'ind_%(domain_id)s_%(column)s_metaphone',
            'ind_%(domain_id)s_%(column)s_soundex',
            '%(domain_id)s_%(column)s_index',
            'search_%(domain_id)s_index'
        ]
        args = ['/usr/bin/indexer', '-c', '/etc/sphinxsearch/sphinx.conf', '--rotate']
        args += [x % index_data for x in indexes]
        # pprint(args)
        upd_out = open('/var/log/sphinxsearch/update_out', 'ab')
        proc = Popen(args, stdin=PIPE, stdout=upd_out, stderr=PIPE)
        out, err = proc.communicate(None)
        upd_out.close()
        if proc.returncode != 0:
            upd_err = open('/var/log/sphinxsearch/update_err', 'ab')
            upd_err.write(err)
            upd_err.write('\n')
            upd_err.close()
            data['result'] = {'error': 'Cannot reindex data for the domain {}.'.format(domain)}
            return formatResponse(data, code)

    except Exception as e:
        data['result'] = {'error': str(e)}
        return formatResponse(data, code)

    data['result'] = {
        'status': 'OK',
        'message': 'Data for the domain {} was reloaded.'.format(domain)
    }
    return formatResponse(data, 200)



# ---------------------------------------------------------
"""
Homepage (content only for debug)
"""
@app.route('/')
def home():
    return render_template('home.html', route='/search', domain='www.maptiler.com')



# ---------------------------------------------------------
"""
Custom template filters
"""
@app.template_filter()
def nl2br(value):
    if isinstance(value, dict):
        for key in value:
            value[key] = nl2br(value[key])
        return value
    elif isinstance(value, str):
        return value.replace('\n', '<br>')
    else:
        return value



# ---------------------------------------------------------
"""
Main launcher
"""
if __name__ == '__main__':
        app.run(threaded=False, host='0.0.0.0', port=8000)
