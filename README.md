# FEA Setup Agent

Upload a STEP file, describe the part's job in a sentence or two, and get a complete ANSYS Static Structural setup: materials, supports, loads, load cases, and mesh, each with a rationale. A deterministic validator checks the proposal, a render shows which faces carry supports and loads, and the download is a Workbench journal plus an HTML report. An eval harness scores the agent against ten reference parts.

Live demo: not yet deployed

## Architecture

STEP → GeometryAnalyzer → Summary Builder (compact JSON) → Proposal Agent (Claude, structured output) → Validator (8 rules, one retry) → Adapter → Journal + Report. Renderer colors the chosen faces. FastAPI serves one page. See `docs/superpowers/specs/2026-09-03-fea-setup-agent-design.md`.

## Eval results

The first live eval run is pending; run the command under "Tests and evals" with an API key set and paste the newest table from evals/results/ here.

Scores are 0 to 1. `load_cases`, `supports`, `loads` are the fraction of reference items matched (by id or an accepted alternative). `material` is family match. `first_pass_valid` is whether the validator passed without a retry. Three runs per part; ± is half the spread.

## Screenshots

Screenshots (render with colored faces, proposal tables, report HTML) will be added after the first live run.

## Run locally

    conda env create -f environment.yml && conda activate fea-agent
    export ANTHROPIC_API_KEY=...
    uvicorn src.web.app:app --reload

On Linux without a display, start Xvfb first and export DISPLAY, or just use the Docker image: `Xvfb :99 -screen 0 1280x1024x24 &  export DISPLAY=:99`

## Run with Docker

    docker build -t fea-agent .
    docker run -p 8000:8000 -e ANTHROPIC_API_KEY=... fea-agent

## Deploy

Pick Fly.io or Render. For Fly:

    fly launch --no-deploy
    fly secrets set ANTHROPIC_API_KEY=...
    fly deploy

Accept the generated `fly.toml` with internal port 8000. Record the public URL in this README. Memory: request at least 2 GB; cadquery plus vtk needs it.

## Tests and evals

    python -m pytest -q
    python -m evals.run_evals --repeats 3

## The original desktop wizard

The PyQt6 wizard this grew out of still lives in `src/wizard` and runs with `python -m src.main`.
