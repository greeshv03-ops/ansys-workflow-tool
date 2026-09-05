FROM mambaorg/micromamba:1.5.8

USER root
RUN apt-get update && apt-get install -y --no-install-recommends xvfb libgl1 libxrender1 libxext6 libsm6 \
    && rm -rf /var/lib/apt/lists/*
USER $MAMBA_USER

COPY --chown=$MAMBA_USER:$MAMBA_USER environment.yml /tmp/environment.yml
RUN micromamba install -y -n base -f /tmp/environment.yml && micromamba clean --all --yes

WORKDIR /app
COPY --chown=$MAMBA_USER:$MAMBA_USER src ./src
COPY --chown=$MAMBA_USER:$MAMBA_USER evals ./evals
COPY --chown=$MAMBA_USER:$MAMBA_USER pyproject.toml README.md ./

ENV PYVISTA_OFF_SCREEN=true
ENV CALLS_PER_SESSION=10
ENV SESSION_CAP_PER_HOUR=50
EXPOSE 8000
CMD ["bash", "-c", "Xvfb :99 -screen 0 1280x1024x24 -nolisten tcp & export DISPLAY=:99; for i in $(seq 1 30); do [ -e /tmp/.X11-unix/X99 ] && break; sleep 0.5; done; [ -e /tmp/.X11-unix/X99 ] || { echo 'Xvfb failed to start on :99' >&2; exit 1; }; exec micromamba run -n base uvicorn src.web.app:app --host 0.0.0.0 --port 8000"]
