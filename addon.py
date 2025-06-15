from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
import os
import re

app = Flask(__name__)
CORS(app)

# --- THE SEARCHABLE CATALOG MANIFEST ---
MANIFEST = {
    "id": "org.yourname.internet-archive.catalog",
    "version": "10.0.2", # Live Search
    "name": "Internet Archive Catalog",
    "description": "Performs a live search of The Internet Archive and shows the results.",
    "types": ["movie", "series"],
    
    "catalogs": [
        {
            "type": "movie", 
            "id": "archive-movies", 
            "name": "Archive Movies",
            # --- THIS IS THE KEY ---
            # This tells Stremio to send search queries to this catalog.
            "behaviorHints": { "searchable": True }
        },
        {
            "type": "series", 
            "id": "archive-series", 
            "name": "Archive Series",
            "behaviorHints": { "searchable": True }
        }
    ],
    
    "resources": ["catalog", "meta", "stream"],
    "idPrefixes": ["archive-"] 
}

# --- LANDING PAGE AND MANIFEST ENDPOINT ---
@app.route('/')
def landing_page():
    host_name = request.host
    return f"""<html><head><title>Internet Archive Catalog</title></head><body><h1>Internet Archive Catalog Addon</h1><p>To install, use this link: <a href="stremio://{host_name}/manifest.json">Install Addon</a></p></body></html>"""

@app.route('/manifest.json')
def get_manifest():
    return jsonify(MANIFEST)

# --- DYNAMIC CATALOG ENDPOINT ---
# This function now handles both browsing AND searching.
@app.route('/catalog/<type>/<id>.json')
def get_catalog(type, id):
    # 'request.args' gets the query parameters from the URL.
    # Stremio sends the user's search query in the 'search' parameter.
    search_query = request.args.get('search', None)
    
    query = ""
    if search_query:
        # If the user is searching, use their query directly.
        print(f"--- INFO: Received search request for: '{search_query}' ---")
        query = search_query
    else:
        # If the user is just browsing, show a default catalog of popular items.
        print(f"--- INFO: No search query. Showing default catalog for '{type}'. ---")
        if type == 'movie':
            query = 'mediatype:(movies) AND downloads:[10000 TO *]'
        else: # 'series'
            query = 'collection:(televisionseries) AND downloads:[5000 TO *]'

    search_url = "https://archive.org/advancedsearch.php"
    params = {
        'q': query,
        'fl[]': 'identifier,title,year',
        'sort[]': 'downloads desc',
        'rows': '100',
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

    print(f"--- SUCCESS: Returning {len(metas)} items for the catalog. ---")
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
    except Exception:
        return jsonify({"meta": {}})

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
    except Exception:
        return jsonify({"streams": []})

    streams = []
    VIDEO_FILE_REGEX = re.compile(r'.*\.(mkv|mp4|avi|mov)$', re.IGNORECASE)
    
    for f in files:
        filename = f.get('name')
        if filename and VIDEO_FILE_REGEX.match(filename):
            streams.append({
                "name": "Internet Archive",
                "title": filename,
                "url": f"https://archive.org/download/{identifier}/{filename.replace(' ', '%20')}"
            })
            
    return jsonify({"streams": sorted(streams, key=lambda k: k['title'])})

if __name__ == "__main__":
    app.run(debug=True)
