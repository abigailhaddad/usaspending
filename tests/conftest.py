"""Make the site BI API importable in tests.

site/api/*.py use bare imports (`from dims import ...`) because on Vercel each
function runs with its own directory on sys.path. Mirror that here so the query
engine and dimension registry can be unit-tested without a running server.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "site", "api"))
