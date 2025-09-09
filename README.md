# CoCon Vote Monitor

A minimal web interface that displays live voting results from a [Televic CoCon](https://www.televic-conference.com/) system. The application is built with [Starlette](https://www.starlette.io/) and communicates with CoCon through the accompanying [`cocon_client`](https://github.com/MarcoMiano/cocon_client) library.

This project is built around the `cocon_client` module. For more information about the client itself see the [cocon_client repository](https://github.com/MarcoMiano/cocon_client).

## Clone the repository

Clone this repository:

```bash
git clone <repo-url>
cd cocon_vote_monitor
```

## Installation

Create a Python environment using either Conda or a virtual environment.

### Option 1: conda

```bash
conda env create -f environment.yml
conda activate cocon_vote_monitor
```

### Option 2: virtualenv + pip

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Option 3.1: OFFLINE - conda
Conda is not required to be installed in the offline machine.

On a machine with internet access:
```bash
# 1. Create the env
conda env create -f environment.yml
conda activate cocon_vote_monitor

# 1.1. OPTIONAL -  make sure pip is up to date
python -m pip install -U pip

# 2. Install conda-pack (one time per system)
conda install -n base -c conda-forge conda-pack

# 3. Pack the full environment
conda-pack -n cocon_vote_monitor -o cocon_vote_monitor.tar.gz
```
Move the *tar.gz to the offline machine (USB stick, SCP, TFTP, whatever)

On the offline machine:
```bash
# 4. Create the env folder and unpack
mkdir -p ~/envs/cocon_vote_monitor
tar -xzf cocon_vote_monitor.tar.gz -C ~/envs/cocon_vote_monitor

# 5. Fix prefixes/paths
~/envs/cocon_vote_monitor/bin/conda-unpack

# 6. Activate the new enviroment
source ~/envs/cocon_vote_monitor/bin/activate
```


### Option 3.2: OFFLINE - virtualenv + offline pip

On a machine with Internet access:

```bash
mkdir packages
pip download -r requirements.txt -d packages
```

Transfer the `packages` directory to the offline machine, then install:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --no-index --find-links packages -r requirements.txt
```

## Running the application

### Development server

Launch the application with hot‑reloading enabled:

```bash
uvicorn cocon_vote_monitor.app:app --reload
```

The server starts on `http://127.0.0.1:8000` by default.

### Production example

For a production setup run Uvicorn without `--reload` and expose it on all interfaces. Increase the number of workers as needed:

```bash
uvicorn cocon_vote_monitor.app:app --host 0.0.0.0 --port 8000 --workers 4
```

You may want to run the above command under a process manager such as `systemd` or `supervisord`.

## Configuration

The CoCon host and port can be adjusted in [`cocon_vote_monitor/app.py`](cocon_vote_monitor/app.py) via the `COCON_HOST` and `COCON_PORT` constants.

## License

This project is licensed under the [GNU Affero General Public License v3.0 or later](https://www.gnu.org/licenses/agpl-3.0-standalone.html).

## Manteiners
Developed and maintained by **3P Technologies Srl**.