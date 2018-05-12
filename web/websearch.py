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
import iso8601
import datetime
import time
import sys
import MySQLdb


app = Flask(__name__, template_folder='templates/')
app.debug = not getenv('WEBSEARCH_DEBUG') is None
app.debug = True

domains = getenv('DOMAINS')
if domains is None or len(domains) < 0:
    raise Exception('Missing required environment variable DOMAINS!')
    sys.exit(1)

# Split domains by comma and prepare source/index for this domain:
# Input data /data/<domain>/search.tsv
# Prepare domain IDs
domains = domains.split(',')
domain_ids = {}
for domain in domains:
    # Check uniqueness and skip duplicates
    if domain_id in domain_ids.values():
        continue
    domain_ids[domain] = domain_id


# Return maximal number of results
SEARCH_MAX_COUNT = 100
SEARCH_DEFAULT_COUNT = 20
if getenv('SEARCH_MAX_COUNT'):
    SEARCH_MAX_COUNT = int(getenv('SEARCH_MAX_COUNT'))
if getenv('SEARCH_DEFAULT_COUNT'):
    SEARCH_DEFAULT_COUNT = int(getenv('SEARCH_DEFAULT_COUNT'))


def get_domain_id(domain):
    # Remove unexpected characters: .:/-,
    return domain.replace('.', '').replace(':', '').replace('/', '').replace('-', '').replace(',', '')


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

    # querylist = query.split(" ")
    # query = "|".join(querylist)

    if count == 0:
        count = SEARCH_DEFAULT_COUNT
    count = min(SEARCH_MAX_COUNT, count)

    repeat = 3
    result = None
    # Repeat 3 times request because of socket.timeout
    while repeat > 0:
        try:
            cl = SphinxClient()
            cl.SetServer(host, port)
            cl.SetConnectTimeout(5.0)       # float seconds
            cl.SetLimits(start, count)      # offset, limit, maxmatches=0, cutoff=0
            # cl.SetSortMode( SPH_SORT_ATTR_DESC, 'date')
            # cl.SetMatchMode(SPH_MATCH_EXTENDED2)
            cl.SetRankingMode(SPH_RANK_SPH04)
            cl.SetFieldWeights({
                'title': 500,
                'content': 1,
                'tags': 20,
            })

            # Prepare filter for query, except tags
            for f in ['date', 'type', 'lang']:
                if f not in query_filter or query_filter[f] is None:
                    continue
                cl.SetFilterString(f, query_filter[f])

            # Prepare sorting by custom or default
            if query_filter['sortBy'] is not None:
                v = query_filter['sortBy']
                if not isinstance(v, list):
                    v = [v]
                sorting = []
                for attr in v:
                    # column-asc/desc
                    attr = attr.split('-')
                    asc = 'ASC'
                    if len(attr) > 1 and (attr[1] == 'desc' or attr[1] == 'DESC'):
                        asc = 'DESC'
                    sorting.append('{} {}'.format(attr[0], asc))
                cl.SetSortMode(SPH_SORT_EXTENDED, ', '.join(sorting))
            else:
                cl.SetSortMode(SPH_SORT_EXTENDED, '@relevance DESC')

            # Prepare date filtering
            datestart = 0
            dateend = 0
            try:
                de = datetime.datetime.utcnow().utctimetuple()
                dateend = int(time.mktime(de))
                if query_filter['datestart'] is not None:
                    ds = iso8601.parse_date(query_filter['datestart']).utctimetuple()
                    datestart = int(time.mktime(ds))
                if query_filter['dateend'] is not None:
                    de = iso8601.parse_date(query_filter['dateend']).utctimetuple()
                    dateend = int(time.mktime(de))
                if datestart > 0 or dateend > 0:
                    cl.SetFilterRange('date_filter', datestart, dateend)
            except Exception as ex:
                print >> sys.stderr, 'Cannot prepare filter range on date: ' + str(ex)
                pass

            # Prepare base query (search except tags)
            if len(query) > 0 and not query.startswith('@'):
                query = '@!tags ' + query
            # Tags contains special prefix
            prefix = ''
            if query_filter['tags'] is not None:
                prefix = '@tags "{}" '.format('" | "'.join(query_filter['tags'].split(',')))

            # Process query under index
            pprint(prefix + query)
            result = cl.Query(prefix + query, index)

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
    return status, prepareResultJson(result, query_filter)



# ---------------------------------------------------------
"""
Process query to Sphinx searchd with mysql
"""
def process_query_mysql(index, query, query_filter, start=0, count=0):
    global SEARCH_MAX_COUNT, SEARCH_DEFAULT_COUNT
    # default server configuration
    host = '127.0.0.1'
    port = 9306
    if getenv('WEBSEARCH_SERVER'):
        host = getenv('WEBSEARCH_SERVER')
    if getenv('WEBSEARCH_SERVER_PORT'):
        port = int(getenv('WEBSEARCH_SERVER_PORT'))

    try:
        db = MySQLdb.connect(host=host, port=port, user='root')
        cursor = db.cursor()
    except Exception as ex:
        result = {
            'total_found': 0,
            'matches': [],
            'message': str(ex),
            'status': False,
            'count': 0,
            'startIndex': start,
        }
        return False, result

    if count == 0:
        count = SEARCH_DEFAULT_COUNT
    count = min(SEARCH_MAX_COUNT, count)

    argsFilter = []
    whereFilter = []

    appended_match = ''
    # Update match query to use query_filter (tags and product)
    for f in ['tags', 'product']:
        if query_filter[f] is None:
            continue
        # construct @<field> (<val1> | <val2>)
        appended_match += ' @{} ({})'.format(
            f,
            ' | '.join(query_filter[f]))

    # Prepare query
    whereFilter.append('MATCH(%s)')
    argsFilter.append(query + appended_match)

    # Prepare filter for query
    for f in ['date', 'type', 'lang']:
        if query_filter[f] is None:
            continue
        inList = []
        for val in query_filter[f]:
            argsFilter.append(val)
            inList.append('%s')
        # Creates where condition: f in (%s, %s, %s...)
        whereFilter.append('{} in ({})'.format(f, ', '.join(inList)))

    sortBy = []
    # Prepare sorting by custom or default
    if query_filter['sortBy'] is not None:
        for attr in query_filter['sortBy']:
            attr = attr.split('-')
            # List of supported sortBy columns - to prevent SQL injection
            if attr[0] not in ('date', 'lang', 'type', 'weight', 'id'):
                print >> sys.stderr, 'Invalid sortBy column ' + attr[0]
                continue
            asc = 'ASC'
            if len(attr) > 1 and (attr[1] == 'desc' or attr[1] == 'DESC'):
                asc = 'DESC'
            sortBy.append('{} {}'.format(attr[0], asc))

    if len(sortBy) == 0:
        sortBy.append('weight DESC')

    # Prepare date filtering in where clause
    datestart = 0
    dateend = 0
    try:
        de = datetime.datetime.utcnow().utctimetuple()
        dateend = int(time.mktime(de))
        if query_filter['datestart'] is not None:
            ds = iso8601.parse_date(query_filter['datestart']).utctimetuple()
            datestart = int(time.mktime(ds))
        if query_filter['dateend'] is not None:
            de = iso8601.parse_date(query_filter['dateend']).utctimetuple()
            dateend = int(time.mktime(de))

        if datestart > 0:
            whereFilter.append('date_filter > %s')
            argsFilter.append(datestart)
        if dateend > 0:
            whereFilter.append('date_filter < %s')
            argsFilter.append(dateend)
    except Exception as ex:
        print >> sys.stderr, 'Cannot prepare filter range on date: ' + str(ex) + str(query_filter)
        pass

    # Field weights and other options
    # ranker=expr('sum(lcs*user_weight)*1000+bm25') == SPH_RANK_PROXIMITY_BM25
    # ranker=expr('sum((4*lcs+2*(min_hit_pos==1)+exact_hit)*user_weight)*1000+bm25') == SPH_RANK_SPH04
    # ranker=expr('sum((4*lcs+2*(min_hit_pos==1)+100*exact_hit)*user_weight)*1000+bm25') == SPH_RANK_SPH04 boosted with exact_hit
    # select @weight+IF(fieldcrc==$querycrc,10000,0) AS weight
    option = "field_weights = (title = 500, content = 1), ranker = sph04, retry_count = 3, retry_delay = 200"
    sql = "SELECT WEIGHT() as weight, * FROM {} WHERE {} ORDER BY {} LIMIT %s, %s OPTION {};".format(
        index,
        ' AND '.join(whereFilter),
        ', '.join(sortBy),
        option
    )

    status = True
    result = {
        'total_found': 0,
        'matches': [],
        'message': None,
    }

    try:
        args = argsFilter + [start, count]
        q = cursor.execute(sql, args)
        pprint([sql, args, cursor._last_executed, q])
        desc = cursor.description
        matches = []
        for row in cursor:
            match = {
                'weight': 0,
                'attrs': {},
                'id': 0,
            }
            for (name, value) in zip(desc, row):
                col = name[0]
                if col == 'id':
                    match['id'] = value
                elif col == 'weight':
                    match['weight'] = value
                else:
                    match['attrs'][col] = value
            matches.append(match)
        # ~ for row in cursor
        result['matches'] = matches

        q = cursor.execute('SHOW META LIKE %s', ('total_found',))
        for row in cursor:
            result['total_found'] = row[1]
    except Exception as ex:
        status = False
        result['message'] = str(ex)

    result['count'] = count
    result['startIndex'] = start
    result['status'] = status
    return status, prepareResultJson(result, query_filter)


# ---------------------------------------------------------
def prepareResultJson(result, query_filter):
    count = result['count']
    response = {
        'results': [],
        'startIndex': result['startIndex'],
        'count': count,
        'totalResults': result['total_found'],
    }
    if 'message' in result and result['message']:
        response['message'] = result['message']

    for row in result['matches']:
        r = row['attrs']
        res = {'rank': row['weight'], 'id': row['id']}
        for attr in r:
            if isinstance(r[attr], str):
                res[attr] = r[attr].decode('utf-8')
            else:
                res[attr] = r[attr]
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

    json = dumps(result)
    mime = 'application/json'
    # Append callback for JavaScript
    if request.args.get('callback'):
        json = request.args.get('callback') + "(" + json + ");"
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
    global domains, domain_ids
    code = 400

    data = {'query': '', 'route': '/search', 'template': 'answer.html'}

    # /search?domain={domain}&q={q}&type=post&lang=en&date=?????&tags=a,b,c
    domain = request.args.get('domain')
    if domain not in domains:
        data['result'] = {'error': 'Domain not allowed!'}
        return formatResponse(data, 403)
    if domain not in domain_ids:
        data['result'] = {'error': 'Duplicated domain is skipped!'}
        return formatResponse(data, 404)
    domain_id = domain_ids[domain]
    data['domain'] = domain

    index = 'search_{}_index'.format(domain_id)
    if request.args.get('index'):
        index = request.args.get('index').encode('utf-8')

    q = request.args.get('q').encode('utf-8')

    query_filter = {
        'type': None, 'lang': None, 'date': None,
        'tags': None, 'datestart': None, 'dateend': None,
        'sortBy': None, 'product': None
    }
    filter = False
    for f in query_filter:
        if request.args.get(f):
            v = None
            # Some arguments may be list
            if f in ('type', 'lang', 'sortBy', 'tags', 'product'):
                vl = request.args.getlist(f)
                if len(vl) == 1:
                    v = vl[0].encode('utf-8')
                    # This argument can be list separated by comma
                    v = v.split(',')
                elif len(vl) > 1:
                    v = [x.encode('utf-8') for x in vl]
            if v is None:
                vl = request.args.get(f)
                v = vl.encode('utf-8')
            query_filter[f] = v
            filter = True

    if not q and not filter:
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
    rc, result = process_query_mysql(index, q, query_filter, start, count)
    if rc:
        code = 200

    data['result'] = result

    # Prepare URLs
    args = dict(request.args)
    if 'startIndex' in args:
        del(args['startIndex'])
    if 'count' in result:
        args['count'] = result['count']
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
@app.route('/update/<path:domain>', methods=['POST'])
def update(domain):
    global domains, domain_ids
    data = {'route': '/update', 'template': None}

    domain = unquote(domain)
    if domain not in domains:
        data['result'] = {'error': 'Domain not allowed!'}
        return formatResponse(data, 403)
    if domain not in domain_ids:
        data['result'] = {'error': 'Duplicated domain is skipped!'}
        return formatResponse(data, 404)

    domain_id = domain_ids[domain].encode('utf-8')
    data['domain'] = domain.encode('utf-8')
    data['protocol'] = 'http'
    if request.args.get('https', None):
        data['protocol'] = 'https'
    url = '%(protocol)s://%(domain)s/search.tsv' % data
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
