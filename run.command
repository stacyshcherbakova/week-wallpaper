#!/bin/bash
# Double-click this in Finder to launch the Weekly Wallpaper app.
cd "$(dirname "$0")" || exit 1
exec uv run streamlit run app.py
