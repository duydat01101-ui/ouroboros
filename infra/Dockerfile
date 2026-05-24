FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        git curl gnupg tini \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
        | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
        > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update && apt-get install -y gh \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN playwright install --with-deps chromium

RUN npm install -g @anthropic-ai/claude-code \
    && claude --version

RUN useradd -m -s /bin/bash ouroboros

COPY . .
RUN git config --global --add safe.directory /app
RUN chown -R ouroboros:ouroboros /app

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "launcher.py"]
