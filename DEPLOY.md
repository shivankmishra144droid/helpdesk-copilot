# Deploying the demo

The root `Dockerfile` builds one container that serves the whole app on port 7860:
Next.js answers the browser and proxies `/api/*` to the FastAPI backend inside the
same container. It runs with `DEMO_MODE=true`, which blocks file uploads, bulk
re-imports and destructive category changes. Search, guided steps and the supervisor
review/approve loop all work. The container's disk is ephemeral, so every restart
resets the demo to the generated data, with four questions waiting in the queue.

The ML stack (PyTorch + sentence-transformers) needs about 1 GB of RAM. That rules
out 512 MB free tiers (Render, Koyeb). A Hugging Face **Docker Space** on the free
CPU tier (16 GB) fits comfortably.

## Before you publish

- Get your supervisor's OK to show this code. All data is synthetic, but the code
  was written during the internship.
- Run the leak check kept outside this repo: `py -3 ..\demo-leak-check\leak_gate.py`
  must print `0 hit(s)`.
- A **public** Space shows its source code in the "Files" tab. Make the Space
  **private** if the code itself shouldn't be public yet; only you can open it then.

## Option A: Hugging Face Space (recommended)

1. Sign in at https://huggingface.co and open **New Space**.
   - Space name: `helpdesk-copilot`
   - SDK: **Docker** → **Blank**
   - Hardware: **CPU basic (free)**
   - Visibility: your choice (see above)
2. Create a token at https://huggingface.co/settings/tokens with **write** access.
3. From this folder:

   ```bash
   git remote add space https://huggingface.co/spaces/<your-username>/helpdesk-copilot
   git push space main
   ```

   When git asks for a password, paste the token. The first build takes about
   15–25 minutes (it also trains the models); the Space page shows the build log.
4. Open `https://<your-username>-helpdesk-copilot.hf.space`.

The YAML block at the top of `README.md` configures the Space (Docker SDK, port 7860).

**Optional AI drafting:** add `ANTHROPIC_API_KEY` (or `OPENAI_API_KEY` + `OPENAI_MODEL`)
under the Space's **Settings → Variables and secrets**. On a public Space anyone can
trigger drafts on your key, so set a spending limit on the provider account first, or
leave it off; drafts then come from the knowledge base.

## Option B: GitHub (code hosting + CI)

1. Create an **empty** repository at https://github.com/new (no README or licence).
   Keep it **private** until the ownership question is settled.
2. From this folder:

   ```bash
   git remote add origin https://github.com/<your-username>/helpdesk-copilot.git
   git push -u origin main
   ```

3. The **Actions** tab runs `.github/workflows/ci.yml`: backend tests, a check that
   committed data matches the generator, and the frontend type-check and build.

You can do both: push to GitHub for the code and CI, and to the Space for the live demo.

## Running the same container locally

```bash
docker build -t helpdesk-copilot .
docker run --rm -p 127.0.0.1:7860:7860 helpdesk-copilot
```

Then open http://localhost:7860. For day-to-day development use `docker compose up`
(separate frontend and backend services) or `run.bat`.
