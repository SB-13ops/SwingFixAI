# SwingFix AI — Setup Guide
### Everything you need to get up and running in under 10 minutes

---

## What's in this folder

```
SwingFixAI/
├── START.bat          ← Double-click this on Windows
├── START.command      ← Double-click this on Mac
├── SETUP GUIDE.md     ← You are here
├── frontend/
│   └── swingfix-ai.html   ← The app (opens in your browser)
└── backend/
    ├── app/
    │   └── main.py        ← The AI analysis engine
    └── requirements.txt   ← List of software dependencies
```

---

## Step 1 — Install Python (one time only)

Python is the engine that runs the AI analysis. You only install this once.

**Windows:**
1. Go to **https://www.python.org/downloads/**
2. Click the big yellow **"Download Python"** button
3. Run the installer
4. ⚠️ On the first screen, check the box that says **"Add Python to PATH"** — this is important
5. Click **Install Now**

**Mac:**
1. Go to **https://www.python.org/downloads/**
2. Download and run the installer
3. Follow the prompts — defaults are fine

**To check it worked:** Open a Terminal (Mac) or Command Prompt (Windows) and type:
```
python --version
```
You should see something like `Python 3.11.4`. Any version 3.9 or higher is fine.

---

## Step 2 — Get your API key (one time only)

The AI coaching reports are powered by Anthropic's Claude. You need a free API key.

1. Go to **https://console.anthropic.com**
2. Sign up for a free account
3. Click **"API Keys"** in the left sidebar
4. Click **"Create Key"**
5. Copy the key — it starts with `sk-ant-...`
6. Keep it somewhere safe (like a notes app) — you'll paste it in Step 3

**Cost:** Analyzing one swing costs roughly **$0.01–$0.03** in API credits. Anthropic gives you free credits to start.

---

## Step 3 — Start the app

**Windows:**
1. Open the `SwingFixAI` folder
2. Double-click **START.bat**
3. A black window opens — paste your API key when asked and press Enter
4. SwingFix AI opens in your browser automatically

**Mac:**
1. Open the `SwingFixAI` folder
2. Right-click **START.command** → click **"Open"**
   *(First time only: Mac will ask if you trust it — click Open)*
3. A terminal window opens — paste your API key when asked and press Enter
4. SwingFix AI opens in your browser automatically

> **First launch takes 2–5 minutes** to install dependencies. After that it starts in seconds.

---

## Step 4 — Use SwingFix AI

Once the app is open in your browser:

1. **Upload your swing videos** — drag and drop up to 3 videos, or click the upload zone
   - Label each as Face-on, Down-the-line, or Front-facing
   - Any video format works (MP4, MOV, etc.)

2. **Scan the QR code** — if you recorded on your phone, scan the QR code to upload directly from your phone without emailing files

3. **Click "Analyze My Swing"** — the analysis takes 15–60 seconds depending on video length

4. **Review your report** — you'll get:
   - A swing score across 5 dimensions (posture, tempo, rotation, balance, club path)
   - Your top 3 faults with explanations
   - 3 specific drills to fix them
   - A visual overlay showing what's happening in your swing
   - Frame-by-frame replay at slow motion

---

## Stopping the app

Just close the black startup window (Windows) or terminal (Mac). The browser tab can stay open but the analysis won't work until you start it again.

---

## Troubleshooting

**"Python is not installed" error**
→ Go back to Step 1. Make sure you checked "Add Python to PATH" during install.

**"Port 8000 already in use" error**
→ Another copy is already running. Close all SwingFix AI windows and try again.

**App opens but analysis never finishes**
→ Your API key might be wrong. Open START.bat in Notepad and check line 3.

**Videos won't upload**
→ Make sure your video files are under 500MB. Shorter clips (5–15 seconds) work best.

**Mac says "cannot be opened because the developer cannot be verified"**
→ Right-click START.command and choose Open (instead of double-clicking).

---

## Running on your local network (optional)

Want to use SwingFix AI on your phone or another device on the same WiFi?

1. Find your computer's IP address:
   - **Windows:** Open Command Prompt, type `ipconfig`, look for "IPv4 Address"
   - **Mac:** System Settings → Network → look for the IP next to "IP Address"

2. On your phone, open a browser and go to:
   ```
   http://YOUR-IP-ADDRESS:8000
   ```
   Example: `http://192.168.1.45:8000`

---

## Want to put it online?

If you want SwingFix AI accessible from anywhere (not just your computer), the easiest option is **Railway**:

1. Go to **https://railway.app** and sign up
2. Upload the `backend` folder
3. Set `ANTHROPIC_API_KEY` as an environment variable
4. Railway gives you a URL like `https://swingfix-abc123.railway.app`
5. In `frontend/swingfix-ai.html`, change line 1 of the script from:
   ```
   var API_BASE = 'http://localhost:8000';
   ```
   to:
   ```
   var API_BASE = 'https://swingfix-abc123.railway.app';
   ```

Estimated cost: ~$5/month on Railway's Hobby plan.

---

*SwingFix AI uses MediaPipe Pose for body tracking and Claude for coaching language.*
*Analysis quality depends on video clarity, lighting, and full-body visibility in frame.*
