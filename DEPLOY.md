# Deploying the demo

The root `Dockerfile` builds one container that serves the whole app on port 7860:
Next.js answers the browser and proxies `/api/*` to the FastAPI backend inside the
same container. It runs with `DEMO_MODE=true`, which blocks file uploads, bulk
re-imports and destructive category changes. Search, guided steps and the supervisor
review/approve loop all work. The container's disk is ephemeral, so every restart
resets the demo to the generated data, with four questions waiting in the queue.

For Render, use `Dockerfile.render` and `render.yaml`. This variant uses the
same MiniLM model through ONNX Runtime, without PyTorch in the serving image.
It keeps hybrid ranking and the intent/outlier models; XGBoost and the optional
cross-encoder are disabled. Training happens in a separate image stage.

## Render free plan

1. Push this synthetic demo repository to a private GitHub repository.
2. Sign in at https://dashboard.render.com using GitHub.
3. Choose **New â†’ Blueprint**, select the repository, and deploy the detected
   `render.yaml`. Confirm the service is on the **Free** plan.
4. Open the assigned `https://helpdesk-copilot-<suffix>.onrender.com` address
   when its build and health check succeed.

The frontend uses Render's assigned `PORT`, and `/api/health` checks the backend.
Model files are downloaded during the build, so startup does not need Hugging Face
authentication. The free service sleeps after 15 minutes without inbound traffic;
waking it takes about a minute and can take longer. Demo edits and queue reviews
are ephemeral and may reset on restart. No paid provider key is configured.

Search comparison and local memory measurements are in
`benchmarks/render_results.json`. Reproduce the comparison with
`python benchmarks/verify_render.py` after installing the training and ONNX requirements.
All 198 top results and expected-answer ranks matched; all 73 backend tests passed.
The production frontend/backend smoke check measured about 439 MB combined RSS. Local Windows RSS
is an estimate only: the combined Linux container must still be checked against
Render's 512 MB limit. A prepared config alone does not confirm deployment.

## Before you publish

- Get your supervisor's OK to show this code. All data is synthetic, but the code
  was written during the internship.
- Run the leak check kept outside this repo: `py -3 ..\demo-leak-check\leak_gate.py`
  must print `0 hit(s)`.
- A **public** Space shows its source code in the "Files" tab. Make the Space
  **private** if the code itself shouldn't be public yet; only you can open it then.

## Alternative: Hugging Face Space

1. Sign in at https://huggingface.co and open **New Space**.
   - Space name: `helpdesk-copilot`
   - SDK: **Docker** â†’ **Blank**
   - Hardware: **CPU basic (free)**
   - Visibility: your choice (see above)
2. Create a token at https://huggingface.co/settings/tokens with **write** access.
3. From this folder:

   ```bash
   git remote add space https://huggingface.co/spaces/<your-username>/helpdesk-copilot
   git push space main
   ```

   When git asks for a password, paste the token. The first build takes about
   15â€“25 minutes (it also trains the models); the Space page shows the build log.
4. Open `https://<your-username>-helpdesk-copilot.hf.space`.

The YAML block at the top of `README.md` configures the Space (Docker SDK, port 7860).

**Optional AI drafting:** add `ANTHROPIC_API_KEY` (or `OPENAI_API_KEY` + `OPENAI_MODEL`)
under the Space's **Settings â†’ Variables and secrets**. On a public Space anyone can
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

Platform references: [Render free services](https://render.com/docs/free),
[Render compute plans](https://render.com/docs/compute-plans),
[Blueprint specification](https://render.com/docs/blueprint-spec).
