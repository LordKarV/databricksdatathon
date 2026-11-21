from dash import Dash, html
app = Dash(__name__)
app.layout = html.Main([html.H1("Find care near you"), html.P("Hello world.")])
if __name__ == "__main__":
    app.run(port=8050, debug=False)
