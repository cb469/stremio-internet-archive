from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
import os
import re

app = Flask(__name__)
CORS(app)

# --- THE TRUE SEARCH PROVIDER MANIFEST ---
# This manifest advertises our addon as a search handler.
MANIFEST = {
    "id": "org.yourname.internet-archive.search-provider",
    "version": "12.0.0",
    "name": "Internet Archive Search",
    "description": "Performs a live search of The Internet Archive.",
    "types": ["movie", "series", "channel"], # Added channel type for broader results
    
    # This is the key: it defines a catalog that REQUIRES a search term.
    # This makes our addon appear as a result provider in Stremio's main search.
    "catalogs": [
        {
            "id": "archive-search",
            "type": "movie", # Stremio needs at least one type here
            "name": "Internet Archive",
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
# This function's only job is to respond to search requests from Stremio.
@app.route('/catalog/<type>/<id>.json')
def get_catalog(type, id):
    search_query = request.args.get('search', None)
    
    if not search_query:
        # If Stremio somehow accesses this without a search, we return nothing.
        return jsonify({"metas": []})

    print(f"--- INFO: Received global search for '{search_query}' ---")
    
    # We build the query exactly as you requested.
    query = f'title:({search_query})'

    search_url = "https://archive.org/advancedsearch.php"
    params = {
        'q': query,
        'fl[]': 'identifier,title,year,mediatype', # Get mediatype to know if it's a movie/series
        'sort[]': 'downloads desc',
        'rows': '50',
        'output': 'json'
    }
    
    try:
        response = requests.get(search_url, params=params)
        response.raise_for_status()
        docs = response.json().get('response', {}).get('docs', [])
    except Exception as e:
        print(f"--- ERROR: Failed to search Archive.org: {e} ---")
        return jsonify({"metas": []})

    metas = []
    for doc in docs:
        identifier = doc.get('identifier')
        if not identifier: continue

        # Determine the type based on the mediatype from the archive
        media_type = doc.get('mediatype', 'movie')
        if media_type in ['televisionseries', 'television']:
            stremio_type = 'series'
        else:
            stremio_type = 'movie'
        
        metas.append({
            "id": f"archive-{identifier}",
            "type": stremio_type,
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
    return jsonify({"meta": { "id": id, "type": type, "name": metadata.get('title', 'Untitled'), "poster": f"https://archive.org/services/get-item-image.php?identifier={identifier}", "background": f"https://archive.org/services/get-item-image.php?identifier={identifier}", "description": metadata.get('description', 'No description available.'), "year": metadata.get('year') }})

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
            streams.append({ "name": "Internet Archive", "title": filename, "url": f"https://archive.org/download/{identifier}/{filename.replace(' ', '%20')}" })
    return jsonify({"streams": sorted(streams, key=lambda k: k['title'])})

if __name__ == "__main__":
    app.run(debug=True)
