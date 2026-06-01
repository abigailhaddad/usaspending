"""/api/colab — turn a reproduce snippet into a one-click Colab notebook.

Colab can't accept inline code via URL, so we create a public GitHub gist containing a
real .ipynb and return its Colab URL (https://colab.research.google.com/gist/<id>). The
notebook is fully parameterized to the user's exact query — open it and Run All to verify.

POST { code: "<python>", title?: "..." } -> { colab_url }
Needs env GH_GIST_TOKEN (a GitHub token with gist scope).
"""
import json
import os
import urllib.request
from http.server import BaseHTTPRequestHandler


DUCKDB_VERSION = "1.5.2"


def make_notebook(sql, title="USAspending — reproducible query"):
    """A runnable notebook built from the exact SQL: install → run (shows the table) →
    a one-cell CSV download. 'Runtime ▸ Run all' reproduces the result and downloads it."""
    def code(src):
        return {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": src}
    def md(src):
        return {"cell_type": "markdown", "metadata": {}, "source": src}
    cells = [
        md([f"# {title}\n",
            "The exact query behind your table, run against the public USAspending dataset on HuggingFace.\n\n",
            "**Runtime ▸ Run all** to reproduce the numbers and download them as CSV."]),
        code([f"!pip install -q duckdb=={DUCKDB_VERSION}\n"]),
        code(["import duckdb\n", "con = duckdb.connect()\n",
              'con.execute("INSTALL httpfs; LOAD httpfs;")\n',
              f'df = con.sql(r"""\n{sql}\n""").df()\n', "df\n"]),
        md(["## Download the data\n", "Run this cell to download the result as a CSV."]),
        code(['df.to_csv("usaspending_result.csv", index=False)\n',
              "from google.colab import files\n",
              'files.download("usaspending_result.csv")\n']),
    ]
    return {"cells": cells,
            "metadata": {"kernelspec": {"name": "python3", "display_name": "Python 3"},
                         "language_info": {"name": "python"}},
            "nbformat": 4, "nbformat_minor": 5}


def make_colab(sql, title=None):
    token = os.environ["GH_GIST_TOKEN"]
    nb = make_notebook(sql, title or "USAspending — reproducible query")
    body = json.dumps({
        "description": "USAspending Table Builder — reproducible query",
        "public": True,
        "files": {"reproduce.ipynb": {"content": json.dumps(nb, indent=1)}},
    }).encode()
    req = urllib.request.Request(
        "https://api.github.com/gists", data=body, method="POST",
        headers={"Authorization": f"Bearer {token}",
                 "Accept": "application/vnd.github+json",
                 "User-Agent": "usaspending-table-builder"})
    gist = json.loads(urllib.request.urlopen(req, timeout=30).read())
    # Colab needs the owner in the path: /gist/<user>/<id>/<filename>
    return (f"https://colab.research.google.com/gist/{gist['owner']['login']}/"
            f"{gist['id']}/reproduce.ipynb")


class handler(BaseHTTPRequestHandler):
    def _send(self, code, body):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(n) or b"{}")
            self._send(200, {"colab_url": make_colab(payload["sql"], payload.get("title"))})
        except Exception as e:
            self._send(400, {"error": str(e)})
