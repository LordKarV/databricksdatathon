| page | requests | transfer KB | decoded KB | repeat-visit KB | ready no throttle s | ready slow 4G s | ready 2G s | external hosts |
|---|---|---|---|---|---|---|---|---|
| streamlit_bare | 9 | 1,249 | 4,664 | 0.8 | 0.38 | 8.12 | 43.47 | - |
| streamlit_probe | 15 | 1,274 | 4,731 | 1.4 | 0.39 | 8.2 | 44.1 | - |
| dash_bare | 12 | 1,467 | 1,465 | 4.5 | 0.12 | 8.52 | 49.86 | - |
| dash_probe | 14 | 1,487 | 1,485 | 5.6 | 0.12 | 8.53 | 49.87 | - |
| gradio_bare | 30 | 992 | 1,003 | 24 | 0.19 | 6.51 | 34.79 | , cdnjs.cloudflare.com, fonts.googleapis.com, fonts.gstatic.com |
| gradio_probe | 64 | 1,125 | 1,126 | 27 | 0.19 | 7.51 | 40.34 | , cdnjs.cloudflare.com, fonts.googleapis.com, fonts.gstatic.com |
| fastapi_bare | 1 | 0.4 | 0.2 | 0.4 | 0.02 | 0.21 | 0.39 | - |
| fastapi_probe | 1 | 1.8 | 3.4 | 1.8 | 0.03 | 0.24 | 0.44 | - |
| dash_probe_gzip | 14 | 343 | 1,485 | 3.3 | 0.12 | 2.49 | 12.72 | - |

| page | lang | geolocation | camera | axe violations (impact x nodes) | targets < 24 px | targets < 44 px |
|---|---|---|---|---|---|---|
| streamlit_bare | en | - | - | aria-allowed-attr (critical x1); button-name (critical x1); region (moderate x1) | a:? 18x18 | button:submit 32x32, a:? 18x18 |
| streamlit_probe | en | works: Got location 12.9716,77.5946 | video=1 file-image=0 capture=0 | aria-allowed-attr (critical x1); button-name (critical x1); region (moderate x4) | a:? 18x18 | button:submit 32x32, a:? 18x18, label:Location (lat,lon) 256x24, input:Location (lat,lon) 254x38, button:Take Photo 256x40 |
| dash_bare |  | - | - | html-has-lang (serious x1) | none | none |
| dash_probe |  | works: Got location 12.9716,77.5946 | video=0 file-image=1 capture=0 | html-has-lang (serious x1); label (critical x1); target-size (serious x1) | button:Use my location 111x21, button:Take a photo (optional) 152x21, input:file 344x21 | button:Use my location 111x21, button:Take a photo (optional) 152x21, input:file 344x21 |
| gradio_bare | en-US | - | - | color-contrast (serious x2); landmark-one-main (moderate x1); region (moderate x1) | button:Use via API 88x21, a:Built with Gradio 122x21 | button:Use via API 88x21, a:Built with Gradio 122x21 |
| gradio_probe | en-US | works: Got location 12.9716,77.5946 | video=1 file-image=1 capture=0 | color-contrast (serious x2); landmark-one-main (moderate x1); region (moderate x3) | button:Upload file 22x22, button:Capture from camera 22x22, button:Use via API 88x21, a:Built with Gradio 122x21 | button:Use my location 296x42, textarea:textarea 270x42, label:Take a photo (optional) 152x26, button:Upload file 22x22, button:Capture from camera 22x22, button:Use via API 88x21, a:Built with Gradio 122x21 |
| fastapi_bare | en | - | - | none | none | none |
| fastapi_probe | en | works: Got location 12.9716,77.5946 | video=0 file-image=1 capture=1 | none | input:file 1x1 | label:Or type a town or PIN code 328x27, input:file 1x1 |
| dash_probe_gzip |  | works: Got location 12.9716,77.5946 | video=0 file-image=1 capture=0 | html-has-lang (serious x1); label (critical x1); target-size (serious x1) | button:Use my location 111x21, button:Take a photo (optional) 152x21, input:file 344x21 | button:Use my location 111x21, button:Take a photo (optional) 152x21, input:file 344x21 |
