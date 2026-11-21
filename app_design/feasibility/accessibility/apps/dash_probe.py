# Dash 2.18 probe: dcc.Geolocation is built in; camera via dcc.Upload(accept=image/*)
# which opens the Android chooser (camera or gallery). No `capture` prop exists.
import os
from dash import Dash, html, dcc, Input, Output
# DASH_COMPRESS=1 turns on gzip; needs the flask-compress package (not pre-installed).
app = Dash(__name__, compress=os.environ.get("DASH_COMPRESS") == "1")
app.layout = html.Main([
    html.H1("Find care near you"),
    html.Button("Use my location", id="b"),
    dcc.Geolocation(id="geo", update_now=False),
    html.P(id="out"),
    dcc.Upload(html.Button("Take a photo (optional)"), id="photo", accept="image/*"),
])

@app.callback(Output("geo", "update_now"), Input("b", "n_clicks"), prevent_initial_call=True)
def ask(_):
    return True

@app.callback(Output("out", "children"), Input("geo", "position"), prevent_initial_call=True)
def show(p):
    return f"Got location {p['lat']:.4f},{p['lon']:.4f}"

if __name__ == "__main__":
    app.run(port=8050, debug=False)
