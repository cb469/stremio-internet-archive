from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
import os
import re

app = Flask(__name__)
CORS(app)

# --- THE TRUE SEARCHABLE CATALOG MANIFEST ---
MANIFEST = {
    "id": "org.yourname.internet-archive.search",
    "version": "10.0.3", # True Search Provider
    "name": "Internet Archive Search",
    "description": "Performs a live search of The Internet Archive and shows the results.",
    "types": ["movie", "series"],
    
    # This structure correctly advertises that we have two catalogs
    # that can and should be used for searching.
    "catalogs": [
        {
            "type": "movie", 
            "id": "archive-search-movies", 
            "name": "Archive Search (Movies)",
            "extra": [{ "name": "search", "isRequired": True }]
        },
        {
            "type": "series", 
            "id": "archive-search-series", 
            "name": "Archive Search (Series)",
            "extra": [{ "name": "search", "isRequired": True }]
        }
    ],
    
    "resources": ["catalog", "meta", "stream"],
    "idPrefixes": ["archive-"] 
}

# --- LANDING PAGE AND MANIFEST ENDPOINT ---
@app.route('/')
def landing_page():
    host_name = request.host
    return f"""<html><head><title>Internet Archive Search</title></head><body><h1>Internet Archive Search Addon</h1><p>To install, use this link: <a href="stremio://{host_name}/manifest.json">Install Addon</a></p></body></html>"""

@app.route('/manifest.json')
def get_manifest():
    return jsonify(MANIFEST)

# --- DYNAMIC SEARCH-ONLY CATALOG ENDPOINT ---
# This function is now ONLY for handling search requests.
@app.route('/catalog/<type>/<id>.json')
def get_catalog(type, id):
    # Get the search query from Stremio.
    search_query = request.args.get('search', None)
    
    # If Stremio is not sending a search query, we return nothing.
    # This addon does not have a "browse" mode.
    if not search_query:
        print("--- INFO: No search query provided. Returning empty catalog. ---")
        return jsonify({"metas": []})

    print(f"--- INFO: Received search request for '{search_query}' in type '{type}' ---")
    
    # We construct a query that searches for the user's text and filters by type.
    # This mirrors your suggestion to search like the archive.org/details/movies page.
    if type == 'movie':
        query = f'({search_query}) AND mediatype:(movies)'
    else: # 'series'
        query = f'({search_query}) AND collection:(televisionseries)'

    search_url = "https://archive.org/advancedsearch.php"
    params = {
        'q': query,
        'fl[]': 'identifier,title,year',
        'sort[]': 'downloads desc',
        'rows': '50', # Limit to a reasonable number of search results
        'output': 'json'
    }
    
    try:
        response = requests.get(search_url, params=params)
        response.raise_for_status()
        docs = response.json().get('response', {}).get('docs', [])
    except Exception as e:
        print(f"--- ERROR: Failed to search Archive.org for catalog: {e} ---")
        return jsonify({"metas": []})

    metas = []
    for doc in docs:
        identifier = doc.get('identifier')
        if not identifier: continue
        
        metas.append({
            "id": f"archive-{identifier}",
            "type": type,
            "name": doc.get('title', 'Untitled'),
            "poster": f"https://archive.org/services/get-item-image.php?identifier={identifier}"
        })

    print(f"--- SUCCESS: Returning {len(metas)} search results. ---")
    return jsonify({"metas": metas})


# --- METADATA AND STREAM ENDPOINTS (Unchanged) ---
@app.route('/meta/<type>/<id>.json')
def get_meta(type, id):
    identifier = id.replace("archive-", "")
    try:
        meta_url = f"https://archive.org/metadata/{identifier}"
        response = requests.get(meta_url)
        response.raise_for_status()
        data = response.json()
    except Exception: return jsonify({"meta": {}})
    metadata = data.get('metadata', {})
    return jsonify({"meta": {
        "id": id, "type": type, "name": metadata.get('title', 'Untitled'),
        "poster": f"https://archive.org/services/get-item-image.php?identifier={identifier}",
        "background": f"https://archive.org/services/get-item-image.php?identifier={identifier}",
        "description": metadata.get('description', 'No description available.'),
        "year": metadata.get('year')
    }})

@app.route('/stream/<type>/<id>.json')
def get_stream(type, id):
    identifier = id.replace("archive-", "")
    try:
        files_url = f"https://archive.org/metadata/{identifier}/files"
        response = requests.get(files_url)
        response.raise_for_status()
        files = response.json().get('result', [])
    except Exception: return jsonify({"streams": []})
    streams = []
    VIDEO_FILE_REGEX = re.compile(r'.*\.(mkv|mp4|avi|mov)$', re.IGNORECASE)
    for f in files:
        filename = f.get('name')
        if filename and VIDEO_FILE_REGEX.match(filename):
            streams.append({
                "name": "Internet Archive", "title": filename,
                "url": f"https://archive.org/download/{identifier}/{filename.replace(' ', '%20')}"
            })
    return jsonify({"streams": sorted(streams, key=lambda k: k['title'])})

if __name__ == "__main__":
    app.run(debug=True)
