# ESM Agent Server — Render Deployment Guide

## Step 1 — Create a GitHub repo for the server

1. Go to github.com → click "+" → "New repository"
2. Name it: `esm-agent-server`
3. Set to **Public**
4. Click "Create repository"
5. Upload these 3 files: `server.py`, `requirements.txt`, `Procfile`

## Step 2 — Deploy on Render

1. Go to https://render.com and sign up (free, no credit card)
2. Click "New +" → "Web Service"
3. Connect your GitHub account
4. Select the `esm-agent-server` repo
5. Fill in:
   - **Name:** `esm-agent-server`
   - **Runtime:** Python 3
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn server:app`
   - **Instance Type:** Free
6. Click "Advanced" → "Add Environment Variable" and add these:
   - `GEMINI_API_KEY` = your AIza... key
   - `GITHUB_TOKEN` = your ghp_... token
   - `GITHUB_REPO` = vijivincent-pixel/Sales-Activity
   - `GITHUB_FILE_PATH` = form.html
   - `GITHUB_BRANCH` = main
7. Click "Create Web Service"
8. Wait ~3 minutes for it to deploy
9. Copy your server URL — looks like: `https://esm-agent-server.onrender.com`

## Step 3 — Add the chat widget to your form

Once you have the server URL, come back here and I'll add
the chat widget to your form.html with that URL hardcoded in.
