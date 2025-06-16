from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
import os
import re

app = Flask(__name__)
CORS(app)

# Configuration
TMDB_API_KEY = os.environ.get('TMDB_API_KEY')
TMDB_API_URL = "https://api.themoviedb.org/3"
REQUEST_TIMEOUT = 5 # Lower timeout for individual requests
MAX_RESULTS_TO_PROCESS = 3 # Process only the top 3 results to avoid timeouts

# manifest
MANIFEST = {
    "id": "org.internet-archive.stream-provider",
    "version": "13.0.1",
    "name": "Internet Archive",
    "description": "Finds streams from The Internet Archive for movies and series.",
    "types": ["movie", "series"],
    "resources": ["stream"],
    "idPrefixes": ["tt"]
}

# --- Landing page, manifest endpoint ---
@app.route('/')
def landing_page():
    host_name = request.host
    return f"""<html><head><title>Internet Archive Addon</title></head><body><h1>Internet Archive Stream Provider</h1><p>This addon attaches to Stremio's existing movie and series pages.</p><p><a href="stremio://{host_name}/manifest.json">Click here to install the addon</a></p></body></html>"""

@app.route('/manifest.json')
def get_manifest():
    return jsonify(MANIFEST)

# --- Streaming logic ---
@app.route('/stream/<type>/<id>.json')
def stream(type, id):
    print(f"--- LOG: Received request for {type} with id {id} ---")
    imdb_id = id.split(':')[0]
    
    title, year = None, None
    if TMDB_API_KEY:
        try:
            tmdb_url = f"{TMDB_API_URL}/find/{imdb_id}?api_key={TMDB_API_KEY}&external_source=imdb_id"
            response = requests.get(tmdb_url, timeout=REQUEST_TIMEOUT)
            if response.status_code == 200:
                data = response.json()
                results = data.get('movie_results' if type == 'movie' else 'tv_results', [])
                if results:
                    item = results[0]
                    title = item.get('title' if type == 'movie' else 'name')
                    year = (item.get('release_date') or item.get('first_air_date', ''))[:4]
                    print(f"--- INFO: TMDB lookup successful: Found '{title} ({year})'. ---")
        except Exception as e:
            print(f"--- WARNING: TMDB lookup failed: {e}. ---")

    found_identifiers = set()

    if title and year:
        print(f"--- INFO ({type.capitalize()}): Performing Title+Year Search... ---")
        query = f'({title}) AND year:({year})'
        results = search_archive(query)
        for result in results: found_identifiers.add(result.get('identifier'))

    print(f"--- INFO (Backup): Performing IMDb ID Search for '{imdb_id}'... ---")
    results = search_archive(f'imdb:{imdb_id}')
    for result in results: found_identifiers.add(result.get('identifier'))
    
    if not found_identifiers:
        print("--- FAIL: No items found on Archive.org from any search. ---")
        return jsonify({"streams": []})

    # Optimization
    identifiers_to_process = list(found_identifiers)[:MAX_RESULTS_TO_PROCESS]
    print(f"--- INFO: Found {len(found_identifiers)} items. Processing top {len(identifiers_to_process)}... ---")

    valid_streams = []
    VIDEO_FILE_REGEX = re.compile(r'.*\.(mkv|mp4|avi|mov)$', re.IGNORECASE)
    
    for identifier in identifiers_to_process:
        if not identifier: continue
        files = get_archive_files(identifier)
        for f in files:
            filename = f.get('name')
            if filename and VIDEO_FILE_REGEX.match(filename):
                if type == 'series':
                    season_num, episode_num = int(id.split(':')[1]), int(id.split(':')[2])
                    patterns = [
                        re.compile(f'[Ss]{season_num:02d}[._- ]?[EeXx]{episode_num:02d}'),
                        re.compile(f'{season_num:d}[xX]{episode_num:02d}'),
                        re.compile(f'[Ss]eason[._- ]{season_num}[._- ]?[Ee]pisode[._- ]{episode_num}', re.I)
                    ]
                    if not any(p.search(filename) for p in patterns):
                        continue
                
                valid_streams.append({ "name": "Internet Archive", "title": filename, "url": f"https://archive.org/download/{identifier}/{filename.replace(' ', '%20')}" })
    
    print(f"--- SUCCESS: Found {len(valid_streams)} valid stream(s). Returning to Stremio. ---")
    return jsonify({"streams": sorted(valid_streams, key=lambda k: k['title'])})

def search_archive(query):
    search_url = "https://archive.org/advancedsearch.php"
    params = {'q': query, 'fl[]': 'identifier', 'rows': '10', 'output': 'json'}
    try:
        response = requests.get(search_url, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json().get('response', {}).get('docs', [])
    except Exception:
        return []

def get_archive_files(identifier):
    metadata_url = f"https://archive.org/metadata/{identifier}"
    try:
        response = requests.get(metadata_url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json().get('files', [])
    except Exception:
        return []

if __name__ == "__main__":
    app.run(debug=True)
