from flask import Flask, jsonify
from flask_cors import CORS
from tmdbv3api import TMDb, Movie, TV
from internetarchive import search_items, get_item
import os
import re

app = Flask(__name__)
CORS(app)

# --- CONFIGURATION ---
# The TMDB API key is essential for this to work.
tmdb = TMDb()
tmdb.api_key = os.environ.get('TMDB_API_KEY')
tmdb.language = 'en'

movie = Movie()
tv = TV()

# --- ADDON MANIFEST (PROVIDER VERSION) ---
# This manifest tells Stremio that we DO NOT have a catalog.
# Instead, we provide 'stream' and 'meta' resources for movies and series.
MANIFEST = {
    "id": "org.yourname.archive-provider",
    "version": "1.2.0",
    "name": "Archive.org Provider",
    "description": "Provides movie and series streams from The Internet Archive.",
    "types": ["movie", "series"],
    "resources": ["stream", "meta"], # We only provide streams and metadata
    "idPrefixes": ["tt"] # Crucial: tells Stremio we respond to IMDb IDs from Cinemeta
}

# --- REGEX FOR FILE MATCHING ---
VIDEO_FILE_REGEX = re.compile(r'.*\.(mkv|mp4|avi|mov)$', re.IGNORECASE)

def search_archive_for_title(title, year):
    """Searches Internet Archive for a given title and year."""
    # Search query is more specific to improve chances of a good match
    search_query = f'collection:movies AND mediatype:movies AND title:("{title}") AND year:{year}'
    try:
        search_results = search_items(search_query, fields=['identifier'])
        # Return the identifier of the first result if found
        return next(iter(search_results), None)
    except Exception as e:
        print(f"ERROR: Failed during Internet Archive search for '{title}': {e}")
        return None

# --- ENDPOINTS ---
@app.route('/manifest.json')
def manifest():
    return jsonify(MANIFEST)

# The '/catalog' endpoint is no longer needed, as we are not providing a catalog.

@app.route('/meta/<type>/<id>.json')
def meta(type, id):
    """
    Stremio asks for metadata. We pass it the TMDB data.
    This is optional but makes the addon feel more integrated.
    """
    if not tmdb.api_key:
        return jsonify({"meta": {}})
    
    try:
        if type == 'movie':
            m = movie.details(external_id=id, external_source='imdb_id')
            meta_obj = {"id": id, "type": "movie", "name": m.title}
        else: # series
            s = tv.details(external_id=id, external_source='imdb_id')
            meta_obj = {"id": id, "type": "series", "name": s.name}
        return jsonify({"meta": meta_obj})
    except Exception as e:
        print(f"ERROR: Failed getting meta for {type} {id}: {e}")
        return jsonify({"meta": {}})


@app.route('/stream/<type>/<id>.json')
def stream(type, id):
    """This is the most important function."""
    if not tmdb.api_key:
        print("ERROR: TMDB_API_KEY is not set. Cannot find streams.")
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
            print(f"WARNING: Not enough info from TMDB for {id}")
            return jsonify({"streams": []})

        print(f"INFO: Searching Archive.org for '{title_to_search}' ({year})")
        archive_item = search_archive_for_title(title_to_search, year)
        
        if not archive_item:
            print(f"INFO: No item found on Archive.org for '{title_to_search}'")
            return jsonify({"streams": []})

        item_id = archive_item['identifier']
        print(f"INFO: Found matching item on Archive.org: {item_id}")
        item_details = get_item(item_id)
        streams = []
        
        for f in item_details.files:
            if VIDEO_FILE_REGEX.match(f['name']):
                # If it's a series, make sure the filename matches SxxExx
                if type == 'series' and s_e_match and not s_e_match.search(f['name']):
                    continue

                streams.append({
                    "name": "Archive.org",
                    "title": f['name'],
                    "url": f"https://archive.org/download/{item_id}/{f['name']}"
                })
        
        return jsonify({"streams": streams})
    except Exception as e:
        print(f"FATAL ERROR in stream function for {id}: {e}")
        return jsonify({"streams": []}) # Return empty list on any error

# Vercel entry point
if __name__ == "__main__":
    app.run(debug=True)
