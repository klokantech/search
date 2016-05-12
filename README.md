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


Example: http://*www.kartenportal.ch*/search.tsv or ugly http://*blog.klokantech.com:8080/beta*/search.tsv

TSV format with fixed columns:
```
url - only stored, not indexed
title - boosted rank fulltext
content - fulltext
type - filter
lang - filter
date - filter
tags - filter on a set + fulltext; comma-separated
```

All in tab separated value. Web must provide correct TSV (no tabs in the content).

## Update endpoint

Endpoint for update of the fulltext index:

```
/update?domain={domain}
```

It downloads http://[domain]/search.tsv and creates index for this domain.

## Search endpoint

```
/search?domain={domain}&q={q}&type=post&lang=en&date=?????&tags=a,b,c
```

Paging via OpenSearch query parameters (`count`, `startIndex`)

a la:
http://mapseries.klokantech.com/ethz/sheets?q=brno&format=json&count=20&startIndex=0&callback=_callbacks_._4io49bdn1

## Results

JSONP or JSON with CORS

```
{
  totalResults: 131,
  results: [ {
      title:, url:, ... 
      ...
      snippet: instead of content ? 
      rank: for debugging ?
    }
  ]
}
```

Related links:
https://developers.google.com/custom-search/json-api/v1/overview#data_format
http://www.opensearch.org/Community/JSON_Formats
