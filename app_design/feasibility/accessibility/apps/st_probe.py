# Streamlit 1.38 probe: camera is native (st.camera_input); geolocation is not.
# The only no-extra-package route is a components.v1.html iframe that writes the
# coordinates into a parent text_input through the DOM. ponytail: deliberate hack,
# the supported route is a bidirectional custom component (e.g. streamlit-js-eval).
import streamlit as st
import streamlit.components.v1 as components

st.title("Find care near you")
loc = st.text_input("Location (lat,lon)", key="loc")
components.html("""
<button id="b" style="min-height:48px;font-size:18px">Use my location</button>
<script>
document.getElementById('b').onclick = () => navigator.geolocation.getCurrentPosition(p => {
  const doc = window.parent.document;
  const inp = doc.querySelector('input[aria-label="Location (lat,lon)"]');
  const setter = Object.getOwnPropertyDescriptor(window.parent.HTMLInputElement.prototype, 'value').set;
  setter.call(inp, p.coords.latitude.toFixed(4) + ',' + p.coords.longitude.toFixed(4));
  inp.dispatchEvent(new Event('input', {bubbles: true}));
  inp.focus(); inp.blur();  // Streamlit commits text_input on blur; a synthetic Enter is ignored
});
</script>""", height=64)
if loc:
    st.write("Got location", loc)
st.camera_input("Take a photo (optional)")
