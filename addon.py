from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
import os
import re

app = Flask(__name__)
CORS(app)

# --- CONFIGURATION ---
TMDB_API_KEY = os.environ.get('TMDB_API_KEY')
TMDB_API_URL = "https://api.themoviedb.org/3"

# --- THE SINGLE, UNIFIED MANIFEST ---
MANIFEST = {
    "id": "org.yourname.internet-archive.final",
    "version": "9.0.3", # Name-Only Search for Series
    "name": "Internet Archive (Final)",
    "description": "A resilient addon for finding movies and series on The Internet Archive.",
    "types": ["movie", "series"],
    "resources": ["stream"],
    "idPrefixes": ["tt"]
}

# --- LANDING PAGE AND MANIFEST ENDPOINT ---
@app.route('/')
def landing_page():
    host_name = request.host
    return f"""<html><head><title>Internet Archive Addon</title></head><body><h1>Internet Archive Addon (Final)</h1><p>To install, use this link: <a href="stremio://{host_name}/manifest.json">Install Addon</a></p></body></html>"""

@app.route('/manifest.json')
def get_manifest():
    return jsonify(MANIFEST)

# --- FINAL, FORKED STREAMING LOGIC ---
@app.route('/stream/<type>/<id>.json')
def stream(type, id):
    print(f"--- LOG: Received request for {type} with id {id} ---")
    imdb_id = id.split(':')[0]
    
    title, year = None, None
    if TMDB_API_KEY:
        try:
            tmdb_url = f"{TMDB_API_URL}/find/{imdb_id}?api_key={TMDB_API_KEY}&external_source=imdb_id"
            response = requests.get(tmdb_url, timeout=5)
            if response.status_code == 200:
                data = response.json()
                results = data.get('movie_results' if type == 'movie' else 'tv_results', [])
                if results:
                    item = results[0]
                    title = item.get('title' if type == 'movie' else 'name')
                    year = (item.get('release_date') or item.get('first_air_date', ''))[:4]
                    print(f"--- INFO: TMDB lookup successful: Found '{title} ({year})'. ---")
            else:
                 print(f"--- WARNING: TMDB API returned status {response.status_code}. ---")
        except Exception as e:
            print(f"--- WARNING: TMDB lookup failed: {e}. ---")
    else:
        print("--- WARNING: TMDB_API_KEY not set. ---")

    found_identifiers = set()

    if type == 'movie':
        # For movies, use the proven Title+Year and IMDb ID search
        print("--- INFO (Movie): Using dual search logic... ---")
        if title and year:
            query = f'({title}) AND year:({year})'
            results = search_archive(query)
            for result in results: found_identifiers.add(result.get('identifier'))
        # The IMDb ID search runs as a backup for movies
        print(f"--- INFO (Movie Backup): Performing IMDb ID Search for '{imdb_id}'... ---")
        results = search_archive(f'imdb:{imdb_id}')
        for result in results: found_identifiers.add(result.get('identifier'))

    else: # type == 'series'
        # --- THIS IS YOUR REQUESTED LOGIC ---
        # For series, we now ONLY search by title.
        print("--- INFO (Series): Using NAME-ONLY search logic... ---")
        if title:
            query = f'({title})'
            results = search_archive(query)
            for result in results: found_identifiers.add(result.get('identifier'))
    
    if not found_identifiers:
        print("--- FAIL: No items found on Archive.org from any search. ---")
        return jsonify({"streams": []})

    print(f"--- INFO: Found {len(found_identifiers)} unique potential item(s). Fetching files... ---")

    valid_streams = []
    VIDEO_FILE_REGEX = re.compile(r'.*\.(mkv|mp4|avi|mov)$', re.IGNORECASE)
    
    for identifier in found_identifiers:
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
    return jsonify({"streams": sorted(_valid_streams, key=lambda k: k['title'])})

def search_archive(query):
    search_url = "https://archive.org/advancedsearch.php"
    params = {'q': query, 'fl[]': 'identifier', 'rows': '10', 'output': 'json'}
    try:
        response = requests.get(search_url, params=params, timeout=10)
        response.raise_for_status()
        return response.json().get('response', {}).get('docs', [])
    except Exception:
        return []

def get_archive_files(identifier):
    metadata_url = f"https://archive.org/metadata/{identifier}"
    try:
        response = requests.get(metadata_url, timeout=10)
        response.raise_for_status()
        return response.json().get('files', [])
    except Exception:
        return []

if __name__ == "__main__":
    app.run(debug=True)
