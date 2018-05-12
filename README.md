# Search

Fulltext search service with JSON API implemented on top of SphinxSearch - for indexing Jekyll websites and blog posts.

Initial deploy on http://search.klokantech.com/

Indexing for projects: 
- Kartenportal.CH (blog or pages)
- MapTiler (how-to + web)
- KlokanTech (blog + web) 

Deployed via docker, system variable DOMAINS defines list of allowed domains (or URL prefixes) for indexing.

Always downloading and indexing the file:
`http://[domain]/search.tsv`


Example: http://www.kartenportal.ch/search.tsv or https://blog.klokantech.com/search.tsv


## Input TSV format

`tsvpipe` has tab character as hardcoded delimiter and has no quoting rules.
Each value is interpreted as string inside sphinxsearch, nevertheless of quotes. Using tab character inside text values is not possible!

TSV format with fixed columns without header line:

```
url - only stored, not indexed
title - boosted rank fulltext
content - fulltext
type - filter
lang - filter
date - filter, in ISO 8601 format: YYYY-MM-DDTHH:MM:SS+HH:MM, required
tags - filter on a set + fulltext; comma-separated
custom_data - only stored, not indexed, no filter
product - filter on a set + fulltext; comma-separated, optional (can be omitted)
```

All in tab separated value. Web must provide correct TSV (**no tabs in the content**).
Note: The `date` column is required, because this component filter via `date_end` by default of the actual time. This allows to create data content in the future (for an example the prepared article, which will be published in the future) without searching in them.

## Update endpoint

Endpoint for update of the fulltext index:

```
POST /update/{domain}
```

It downloads http://[domain]/search.tsv and creates index for this domain.

## Search endpoint

```
GET /search?domain={domain}&q={q}&type=post&lang=en&date=?????&tags=a,b,c
```

Paging via OpenSearch query parameters (`count`, `startIndex`)

ala:
http://mapseries.klokantech.com/ethz/sheets?q=brno&format=json&count=20&startIndex=0&callback=_callbacks_._4io49bdn1

## Results

JSONP or JSON with CORS

```
{
  "count": 20,
  "nextIndex": 20,
  "startIndex": 0,
  "totalResults": 31,
  "results": [
    {
      "lang": "en",
      "tags": "<tags>",
      "url": "<url>",
      "title": "<title>",
      "rank": 31548,
      "content": "xxx",
      "date": "2016-05-19T11:06:41+02:00",
      "date_filter": 1463648801.0,
      "type": "<type>",
      "custom_data": "xxx",
      "id": 21
    },
  ]
}
```

Related links:
https://developers.google.com/custom-search/json-api/v1/overview#data_format
http://www.opensearch.org/Community/JSON_Formats
