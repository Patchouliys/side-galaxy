# Tests and Checks

Run the following commands from the repository root. Requirements are Python 3.11+, uv, and Node.js / npm for OpenSpec.

## Install Development Dependencies

```sh
uv sync --frozen
npm ci --ignore-scripts
```

## Automated Tests and Specification Checks

```sh
uv run python -m unittest discover -s tests -v
npm run spec:validate
node --check src/side_galaxy/static/app.js
node --check src/side_galaxy/static/homepage.js
```

To select a test file, for example:

```sh
uv run python -m unittest discover -s tests -p 'test_execution_transport.py' -v
```

## HTTP, CLI, MCP, and Agent Integration

Start a separate demo database in one terminal:

```sh
uv run sg serve --demo --db .data/integration.db
```

In another terminal, run:

```sh
uv run python scripts/check_integration.py
```

The script registers a synthetic agent with the demo service, uploads a bundle, and creates experiment records. The default address is `http://127.0.0.1:7980`; set `SG_SERVER` when using another local demo port.

## Build and Deployment Configuration

```sh
uv build
ansible-playbook --syntax-check -i deploy/inventory.example.yml deploy/agents.yml
```

Ansible syntax checks require Ansible on the control machine.
