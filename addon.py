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

# --- SERIES-ONLY MANIFEST ---
# This is the key. By only declaring "series", we give Stremio a simple
# manifest that it cannot misinterpret, based on our successful debug test.
MANIFEST = {
    "id": "org.yourname.internet-archive-series-final",
    "version": "8.0.0",
    "name": "Internet Archive (Series Only)",
    "description": "A dedicated addon to find TV Series on The Internet Archive.",
    "types": ["series"], # This is the most important line
    "resources": ["stream"],
    "idPrefixes": ["tt"]
}

# --- LANDING PAGE AND MANIFEST ENDPOINT ---
@app.route('/')
def landing_page():
    host_name = request.host
    return f"""
    <html>
        <head><title>Internet Archive Series Addon</title></head>
        <body>
            <h1>Internet Archive (Series Only) Addon</h1>
            <p><strong>This addon ONLY searches for TV shows.</strong></p>
            <p><a href="stremio://{host_name}/manifest.json">Click here to install the addon</a></p>
        </body>
    </html>
    """

@app.route('/manifest.json')
def get_manifest():
    return jsonify(MANIFEST)


# --- DEDICATED SERIES STREAMING LOGIC ---
@app.route('/stream/series/<id>.json') # Route is now hardcoded for series
def stream_series(id):
    print(f"--- LOG: Received request for SERIES with id {id} ---")
    imdb_id = id.split(':')[0]
    
    title, year = None, None
    if TMDB_API_KEY:
        try:
            tmdb_url = f"{TMDB_API_URL}/find/{imdb_id}?api_key={TMDB_API_KEY}&external_source=imdb_id"
            response = requests.get(tmdb_url, timeout=5)
            if response.status_code == 200:
                data = response.json()
                results = data.get('tv_results', [])
                if results:
                    item = results[0]
                    title = item.get('name')
                    year = item.get('first_air_date', '')[:4]
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
