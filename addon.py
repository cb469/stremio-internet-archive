from flask import Flask, jsonify
from flask_cors import CORS
from tmdbv3api import TMDb, Movie, TV
from internetarchive import search_items, get_item
import os
import re

app = Flask(__name__)
CORS(app)

# --- CONFIGURATION ---
tmdb = TMDb()
tmdb.api_key = os.environ.get('TMDB_API_KEY')
tmdb.language = 'en'

movie = Movie()
tv = TV()

# --- ADDON MANIFEST ---
MANIFEST = {
    "id": "org.yourname.archive-provider",
    "version": "1.3.0", # Incremented version
    "name": "Archive.org Provider",
    "description": "Provides movie and series streams from The Internet Archive.",
    "types": ["movie", "series"],
    "resources": ["stream"], # We only need to declare 'stream'
    "idPrefixes": ["tt"]
}

# --- REGEX FOR FILE MATCHING ---
VIDEO_FILE_REGEX = re.compile(r'.*\.(mkv|mp4|avi|mov)$', re.IGNORECASE)

# --- NEW, MORE FLEXIBLE SEARCH FUNCTION ---
def search_archive(title, year):
    """
    Searches Internet Archive with a more flexible keyword-based query.
    """
    # This query searches for the title and year as keywords, which is more reliable.
    search_query = f'({title} {year}) AND mediatype:movies'
    try:
        # We only care about the top result for a given movie/year.
        search_results = search_items(search_query, fields=['identifier'])
        return next(iter(search_results), None)
    except Exception as e:
        print(f"ERROR: Failed during Internet Archive search for '{title}': {e}")
        return None

# --- ENDPOINTS ---
@app.route('/manifest.json')
def manifest():
    return jsonify(MANIFEST)

@app.route('/stream/<type>/<id>.json')
def stream(type, id):
    if not tmdb.api_key:
        print("FATAL: TMDB_API_KEY is not set. Cannot provide streams.")
        return jsonify({"streams": []})

    try:
        title_to_search = None
        year = None
        s_e_match = None

        if type == 'movie':
            imdb_id = id
            m = movie.details(external_id=imdb_id, external_source='imdb_id')
            title_to_search = m.title
            year = m.release_date.split('-')[0] if m.release_date else None
        else: # series
            imdb_id, season_num, episode_num = id.split(':')
            s = tv.details(external_id=imdb_id, external_source='imdb_id')
            title_to_search = s.name
            year = s.first_air_date.split('-')[0] if s.first_air_date else None
            s_e_match = re.compile(f'S{int(season_num):02d}E{int(episode_num):02d}', re.IGNORECASE)

        if not title_to_search or not year:
            return jsonify({"streams": []})

        print(f"INFO: Searching Archive.org for '{title_to_search}' ({year})")
        archive_item = search_archive(title_to_search, year)
        
        if not archive_item:
            print(f"INFO: No item found on Archive.org for '{title_to_search}'")
            return jsonify({"streams": []})

        item_id = archive_item['identifier']
        print(f"INFO: Found matching item on Archive.org: {item_id}")
        item_details = get_item(item_id)
        streams = []
        
        for f in item_details.files:
            if VIDEO_FILE_REGEX.match(f['name']):
                if type == 'series' and s_e_match and not s_e_match.search(f['name']):
                    continue

                streams.append({
                    "name": "Archive.org",
                    "title": f.get('title', f['name']), # Use file title if available
                    "url": f"https://archive.org/download/{item_id}/{f['name']}"
                })
        
        print(f"INFO: Found {len(streams)} stream(s) for {item_id}")
        return jsonify({"streams": streams})
    except Exception as e:
        print(f"FATAL ERROR in stream function for {id}: {e}")
        return jsonify({"streams": []})

# Vercel entry point
if __name__ == "__main__":
    app.run(debug=True)
