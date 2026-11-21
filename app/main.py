"""Databricks Apps entry point: serve on the port the platform assigns.

Databricks Apps sets DATABRICKS_APP_PORT; 8000 is the local default. The access log stays off because
request lines can carry the service and a rounded point (spec section 8, Safety 7.3).
"""
import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=int(os.environ.get("DATABRICKS_APP_PORT", "8000")),
                access_log=False)
