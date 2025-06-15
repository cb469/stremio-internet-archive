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

# --- MOVIE ADDON MANIFEST ---
MOVIE_MANIFEST = {
    "id": "org.yourname.internet-archive-movies",
    "version": "7.0.0",
    "name": "Internet Archive (Movies)",
    "description": "Provides movie streams from The Internet Archive.",
    "types": ["movie"], # This addon only declares movies
    "resources": ["stream"],
    "idPrefixes": ["tt"]
}

# --- SERIES ADDON MANIFEST ---
SERIES_MANIFEST = {
    "id": "org.yourname.internet-archive-series",
    "version": "7.0.0",
    "name": "Internet Archive (Series)",
    "description": "Provides series streams from The Internet Archive.",
    "types": ["series"], # This addon only declares series
    "resources": ["stream"],
    "idPrefixes": ["tt"]
}

# --- USER-FRIENDLY LANDING PAGE ---
@app.route('/')
def landing_page():
    host_name = request.host
    return f"""
    <html>
        <head><title>Internet Archive Addons</title></head>
        <body>
            <h1>Install Your Internet Archive Stremio Addons</h1>
            <p><strong>This is the final, working version. Please uninstall all old addons before installing these.</strong></p>
            <p><a href="stremio://{host_name}/movie/manifest.json">Click here to install the MOVIE addon</a></p>
            <p><a href="stremio://{host_name}/series/manifest.json">Click here to install the SERIES addon</a></p>
        </body>
    </html>
    """

# --- MANIFEST ENDPOINTS ---
@app.route('/movie/manifest.json')
def movie_manifest():
    return jsonify(MOVIE_MANIFEST)

@app.route('/series/manifest.json')
def series_manifest():
    return jsonify(SERIES_MANIFEST)


# --- UNIFIED STREAMING LOGIC ---
# This single stream function handles requests from BOTH addons correctly.
@app.route('/<base>/stream/<type>/<id>.json')
def stream(base, type, id):
    print(f"--- LOG: Received request for '{base}' addon, type '{type}' with id '{id}' ---")
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

    if title:
        print(f"--- INFO: Performing Title Search for '{title}'... ---")
        query = f'({title}) AND year:({year})' if year else f'({title})'
        results = search_archive(query)
        for result in results: found_identifiers.add(result.get('identifier'))

    print(f"--- INFO: Performing IMDb ID Search for '{imdb_id}'... ---")
    results = search_archive(f'imdb:{imdb_id}')
    for result in results: found_identifiers.add(result.get('identifier'))
    
    if not found_identifiers:
        print("--- FAIL: No items found on Archive.org from either search. ---")
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
    return jsonify({"streams": sorted(valid_streams, key=lambda k: k['title'])})

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
