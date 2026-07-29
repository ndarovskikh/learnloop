# LearnLoop

## 1. Check Python, Node.js, npm, and Git

Before cloning or running the project, open a terminal and check the installed
versions:

```bash
python3 --version
node --version
npm --version
git --version
```

LearnLoop requires:

- Python 3.9 or newer;
- Node.js 18 or newer;
- npm;
- Git;
- an OpenCode API key.

If all four commands print compatible versions, continue to step 2.

### Install missing software

macOS with [Homebrew](https://brew.sh/):

```bash
brew install python node git
```

Windows PowerShell:

```powershell
winget install Python.Python.3.12
winget install OpenJS.NodeJS.LTS
winget install Git.Git
```

Close and reopen PowerShell after installation. On Windows, the Python command
may be `python` or `py` instead of `python3`.

Ubuntu or Debian:

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip nodejs npm git
```

After installing, run the four version checks again.

## 2. Get the project

Clone the repository and enter the main project directory:

```bash
git clone git@github.com:ndarovskikh/learnloop.git
cd learnloop
```

If the repository is already on your computer, open a terminal in its
`learnloop` directory. All commands below start from this directory unless a
step says otherwise.

The project contains two applications:

```text
learnloop/
├── backend/   Python, FastAPI, agent loop, tools, progress and course data
└── frontend/  Vue 3 course library, chat workspace and learning analytics
```

### Minimal memory demo

The three memory types can be exercised without an API key:

```bash
PYTHONPATH=backend/src python -m learnloop --memory-demo
```

It writes a scored attempt and calculated topic mastery to SQLite, then writes
one coach observation to JSONL. In the running application the same storage is
created automatically at `backend/data/learnloop.sqlite3` and
`backend/data/learning_memories.jsonl`; no database server is required. Check
the persistent records with:

```bash
PYTHONPATH=backend/src python3 -m learnloop --memory-status --user natali
sqlite3 backend/data/learnloop.sqlite3 '.tables'
```

The permanent trainer rules are in
[`backend/coach_rules.md`](backend/coach_rules.md).

### LLM context

Every model call receives a small push-context: coach rules, privacy rules,
student and course identifiers, active topic/question, topic mastery, and the
last three exchanges. Detailed data stays pull-only. The registered pull tools
are `retrieve_learning_memory`, `get_topic_mastery`, `get_previous_attempts`,
and `get_course_material`; each student-memory request is scoped to its own
`user_id`.

### Admin statistics agent

The privileged `AdminStatisticsAgent` can calculate only an authenticated
student's anonymized course or topic percentile. Configure
`LEARNLOOP_ADMIN_TOKEN` in `backend/.env`, then call
`POST /api/admin/benchmark` with an `X-Admin-Token` header. It is disabled by
default, is not available to the ordinary coaching tools, and refuses cohorts
smaller than two. The full privacy boundary is in
[`docs/admin-agent-boundary.md`](docs/admin-agent-boundary.md).

### Personal question-bank agent

After a student completes at least 5% of the course, LearnLoop can generate a
private batch of five practice questions from that student's SQLite progress
and weakest knowledge area. At the topic checkpoint the student can request
the batch with **Generate 5 practice questions**. These questions are stored in
SQLite and cannot be served to another student.

The same agent can be called once a night by the system cron. For a 03:00 run
in mainland Spain, add this to the crontab (adjust the project and Python paths):

```cron
CRON_TZ=Europe/Madrid
0 3 * * * cd /path/to/learnloop && /path/to/python -m learnloop --generate-nightly-questions
```

`Europe/Madrid` automatically follows CET/CEST (UTC+1/UTC+2). To use the
machine's configured local time instead, omit `CRON_TZ`.

When nobody has progress, or a student's course completion is below 5%, the
nightly command intentionally writes nothing to stdout and exits successfully.
The decision is still recorded in SQLite table `question_generation_logs` with
status `silent`, the reason, completion value, trigger, and timestamp.

## 3. Install all backend dependencies

Create an isolated Python environment:

```bash
python3 -m venv .venv
```

Activate it on macOS or Linux:

```bash
source .venv/bin/activate
```

Activate it on Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

Install the backend and all Python dependencies:

```bash
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e backend --no-build-isolation
```

This installs FastAPI, Uvicorn, the OpenAI-compatible client, and LearnLoop
itself. Check the installation:

```bash
python -m pip check
python -c "import fastapi, openai, uvicorn, learnloop; print('Backend dependencies: OK')"
```

## 4. Install all frontend dependencies

From the `learnloop` directory:

```bash
cd frontend
npm ci
cd ..
```

`npm ci` installs the exact Vue and Vite versions recorded in
`frontend/package-lock.json`.

## 5. Configure OpenCode

Create a private environment file:

macOS or Linux:

```bash
cp backend/.env.example backend/.env
```

Windows PowerShell:

```powershell
Copy-Item backend/.env.example backend/.env
```

Open `backend/.env` and replace the placeholder with your OpenCode API key:

```text
OPENAI_API_KEY=insert api key here
OPENAI_MODEL=mimo-v2.5-free
OPENAI_BASE_URL=https://opencode.ai/zen/v1
MAX_AGENT_STEPS=12
MAX_TOPIC_DEPTH=5
MAX_EXTRA_TOPIC_ITERATIONS=1
```

Never commit `backend/.env`. It contains a secret and is ignored by Git.

## 6. Add the course PDF

Place the book at this exact path and filename:

```text
backend/data/materials/ddia.pdf
```

The PDF is stored locally and ignored by Git. LearnLoop starts without it, but
the material cannot be opened from the course sidebar.

## 7. Start the backend with hot reload

Use the first terminal. Make sure you are in `learnloop` and the Python virtual
environment is active:

```bash
source .venv/bin/activate
python -m uvicorn learnloop.api:app --reload --app-dir backend/src --host 127.0.0.1 --port 8000
```

On Windows, replace the first command with:

```powershell
.venv\Scripts\Activate.ps1
```

Keep this terminal open. Uvicorn automatically restarts the backend whenever a
Python source file changes.

Backend addresses:

- API: http://127.0.0.1:8000
- interactive API documentation: http://127.0.0.1:8000/docs

## 8. Start the frontend with hot reload

Open a second terminal:

```bash
cd <path-to-learnloop>/frontend
npm run dev
```

Keep this terminal open and open http://127.0.0.1:5173 in a browser. Vite
automatically refreshes the frontend whenever a Vue, JavaScript, or CSS file
changes.

You should see the course library. Select the DDIA course to open its materials,
adaptive chat, and learning analytics.

### Demo accounts

Use one of the team accounts on the login screen:

| Username | Password |
| --- | --- |
| `natali` | `1234` |
| `liza` | `1234` |
| `danya` | `1234` |
| `andrew` | `1234` |

Each username has independent learning progress stored locally by the backend.
These credentials are intentionally hardcoded for the course demo and must not be
used as production authentication.

## 9. Stop the application

Press `Ctrl+C` in the frontend terminal and then in the backend terminal.

## Start it again later

The dependencies only need to be installed once.

Terminal 1, from the `learnloop` directory:

```bash
source .venv/bin/activate
python -m uvicorn learnloop.api:app --reload --app-dir backend/src --host 127.0.0.1 --port 8000
```

Terminal 2:

```bash
cd <path-to-learnloop>/frontend
npm run dev
```

Then open http://127.0.0.1:5173.

## Troubleshooting

- `python3: command not found`: install Python using step 1. On Windows, try
  `python` or `py` instead.
- Virtual environment creation fails on Ubuntu: run
  `sudo apt install python3-venv` and repeat step 3.
- `No module named uvicorn` or `No module named learnloop`: activate `.venv`
  and repeat the backend installation commands from step 3.
- `npm: command not found`: install Node.js using step 1, then reopen the
  terminal.
- The page opens but no course data appears: verify that the backend terminal is
  running and http://127.0.0.1:8000/docs opens.
- The AI request fails: verify the three `OPENAI_*` values in `backend/.env`.
- The PDF does not open: verify that its path is exactly
  `backend/data/materials/ddia.pdf`.
- Port 8000 or 5173 is busy: stop the older process with `Ctrl+C`.

## Tests and production build

Run backend tests from the `learnloop` directory:

```bash
.venv/bin/python -m unittest discover -s backend/tests -v
```

Build the frontend:

```bash
cd frontend
npm run build
```

## What LearnLoop does

LearnLoop is an adaptive AI learning coach. It checks a student's answers,
saves progress, identifies knowledge gaps, and adapts the next question. The
current demo course is based on *Designing Data-Intensive Applications*.
