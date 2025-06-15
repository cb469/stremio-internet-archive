from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
import os
import re

app = Flask(__name__)
CORS(app)

# --- THE CORRECTED UNIFIED CATALOG MANIFEST ---
MANIFEST = {
    "id": "org.yourname.internet-archive.catalog",
    "version": "10.0.1", # Manifest Fix
    "name": "Internet Archive Catalog",
    "description": "Browse movies and series directly from The Internet Archive.",
    "types": ["movie", "series"],
    
    # --- THIS IS THE FIX ---
    # The 'catalogs' property is now correctly defined. This tells Stremio
    # exactly which catalogs we offer, with their own names and IDs.
    "catalogs": [
        {"type": "movie", "id": "archive-movies", "name": "Archive Movies"},
        {"type": "series", "id": "archive-series", "name": "Archive Series"}
    ],
    
    # 'resources' now correctly lists the features we support.
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

# --- CATALOG ENDPOINT ---
# This function builds the poster grid you see in Stremio.
@app.route('/catalog/<type>/<id>.json')
def get_catalog(type, id):
    print(f"--- LOG: Request received for catalog: {type}/{id} ---")
    
    # This check ensures we only run for our defined catalog IDs.
    if id not in ["archive-movies", "archive-series"]:
        return jsonify({"metas": []})

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


# --- METADATA ENDPOINT ---
@app.route('/meta/<type>/<id>.json')
def get_meta(type, id):
    identifier = id.replace("archive-", "")
    
    try:
        meta_url = f"https://archive.org/metadata/{identifier}"
        response = requests.get(meta_url)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        print(f"--- ERROR: Failed to get metadata for {identifier}: {e} ---")
        return jsonify({"meta": {}})

    metadata = data.get('metadata', {})
    
    meta_obj = {
        "id": id,
        "type": type,
        "name": metadata.get('title', 'Untitled'),
        "poster": f"https://archive.org/services/get-item-image.php?identifier={identifier}",
        "background": f"https://archive.org/services/get-item-image.php?identifier={identifier}",
        "description": metadata.get('description', 'No description available.'),
        "year": metadata.get('year')
    }
    
    return jsonify({"meta": meta_obj})


# --- STREAM ENDPOINT ---
@app.route('/stream/<type>/<id>.json')
def get_stream(type, id):
    identifier = id.replace("archive-", "")
    print(f"--- LOG: Request received for streams for item: {identifier} ---")

    try:
        files_url = f"https://archive.org/metadata/{identifier}/files"
        response = requests.get(files_url)
        response.raise_for_status()
        files = response.json().get('result', [])
    except Exception as e:
        print(f"--- ERROR: Failed to get files for {identifier}: {e} ---")
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
            
    print(f"--- SUCCESS: Found {len(streams)} video files for item. ---")
    return jsonify({"streams": sorted(streams, key=lambda k: k['title'])})

if __name__ == "__main__":
    app.run(debug=True)
