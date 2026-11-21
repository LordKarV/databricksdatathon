# Gradio 4.44 probe: camera is native (gr.Image sources webcam); geolocation via the
# built-in `js=` hook on an event, no custom component.
import gradio as gr
GEO_JS = """() => new Promise(r => navigator.geolocation.getCurrentPosition(
  p => r('Got location ' + p.coords.latitude.toFixed(4) + ',' + p.coords.longitude.toFixed(4))))"""
with gr.Blocks() as demo:
    gr.Markdown("# Find care near you")
    b = gr.Button("Use my location")
    loc = gr.Textbox(label="Location")
    b.click(None, None, loc, js=GEO_JS)
    gr.Image(sources=["webcam", "upload"], type="filepath", label="Take a photo (optional)")
demo.launch(server_port=7860)
