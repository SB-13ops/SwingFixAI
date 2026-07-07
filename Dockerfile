# Sharing SwingFix AI with friends

No Anthropic account or API key is needed by anyone. The API key is optional
and only upgrades the coaching text from the built-in engine to AI-written.

## Option 1 - Send them the zip (they run it on their PC)
1. Send the SwingFixAI zip
2. They install Python from python.org (check "Add Python to PATH")
3. They double-click START.bat and press Enter to skip the API key
4. Full analysis, skeleton, pro overlay, scores, drills, and reports all work

## Option 2 - Same WiFi (easiest for in-person)
1. You run START.bat on your PC
2. Find your IP: open Command Prompt, type: ipconfig  (look for IPv4 Address)
3. Anyone on your WiFi visits  http://YOUR-IP:8000  from their phone or laptop
4. First time, allow Python through Windows Firewall when prompted

## Option 3 - Host it online (share a link with anyone, anywhere)
Using Render (free tier works):
1. Put this folder in a GitHub repository
2. Go to render.com -> New -> Web Service -> connect the repo
3. Environment: Docker (it finds the Dockerfile automatically)
4. Optional: add ANTHROPIC_API_KEY as an environment variable for AI coaching
5. Render gives you a URL like https://swingfix.onrender.com - share that

Railway (railway.app) works the same way: New Project -> Deploy from GitHub.
Expect roughly $5/month on paid tiers; Render's free tier sleeps when idle
(first visit after a while takes ~1 minute to wake up).

Note: on a public URL, the QR phone-upload works from anywhere, not just
your WiFi, since the server is on the internet.
