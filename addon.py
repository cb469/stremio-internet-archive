from flask import Flask, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# --- MANIFEST FOR A SERIES-ONLY ADDON ---
# This is the simplest possible manifest to test series functionality.
# If this works, we know the problem was manifest complexity.
MANIFEST = {
    "id": "org.yourname.internet-archive-series-debug",
    "version": "3.0.0",
    "name": "Series Debug Test",
    "description": "A minimal addon to test if series requests are received.",
    "types": ["series"],       # CRITICAL: We only support series.
    "resources": ["stream"],
    "idPrefixes": ["tt"]
}

# A standard, public domain video for testing.
DUMMY_STREAM = {
    "name": "Debug Stream",
    "title": "Big Buck Bunny Test",
    "url": "http://distribution.bbb3d.renderfarming.net/video/mp4/bbb_sunflower_1080p_30fps_normal.mp4"
}

@app.route('/manifest.json')
def manifest():
    # When Stremio installs, it will see we ONLY handle series.
    print("--- LOG: Manifest requested. Declaring SERIES-ONLY support. ---")
    return jsonify(MANIFEST)

@app.route('/stream/<type>/<id>.json')
def stream(type, id):
    # This function now has one job: if Stremio asks for a series,
    # prove it by returning the dummy stream.
    print(f"--- LOG: Stream request received for type '{type}' with id '{id}' ---")

    if type == 'series':
        print("--- SUCCESS: Stremio is asking for a SERIES stream! Returning the debug video. ---")
        return jsonify({"streams": [DUMMY_STREAM]})
    else:
        # This part should never be reached if the manifest is working.
        print(f"--- WARNING: Received an unexpected request for type '{type}'. Ignoring. ---")
        return jsonify({"streams": []})

if __name__ == "__main__":
    app.run(debug=True)
