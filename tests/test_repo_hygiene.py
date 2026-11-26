"""Cheap checks that catch the build/config mistakes found in the November review."""

import ast
import os
import re

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
KNOWN_SCRAPERS = {"comeet", "greenhouse", "lever", "checkpoint", "amazon"}


def _read(*parts):
    with open(os.path.join(ROOT, *parts), "rb") as f:
        return f.read()


def _seed_sites():
    tree = ast.parse(_read("seed_comeet_discovery.py").decode("utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "SITES":
            return ast.literal_eval(node.value)
    raise AssertionError("SITES not found")


def test_seed_list_has_no_duplicates_and_known_scrapers():
    sites = _seed_sites()
    urls = [url for _, _, url in sites]
    assert len(urls) == len(set(urls)), "a company is listed twice"
    for display, name, _ in sites:
        assert display.strip(), "every source needs a company name"
        assert name in KNOWN_SCRAPERS, name


def test_requirements_are_utf8_and_cover_the_worker_imports():
    raw = _read("requirements.txt")
    text = raw.decode("utf-8")          # raises if someone saves it as UTF-16 again
    names = {re.split(r"[<>=!~\[ ]", line.strip(), maxsplit=1)[0].lower()
             for line in text.splitlines() if line.strip() and not line.startswith("#")}
    for needed in ("aiohttp", "beautifulsoup4", "lxml", "sqlalchemy", "google-cloud-pubsub", "psycopg2-binary"):
        assert needed in names, needed


def test_dockerfile_installs_correctly_and_runs_a_real_file():
    lines = _read("Dockerfile").decode("utf-8").splitlines()
    pip = next(line for line in lines if "pip install" in line)
    assert "-r --" not in pip, "a flag right after -r is read as the requirements file name"
    workdirs = [line.split()[1] for line in lines if line.startswith("WORKDIR")]
    cmd = next(line for line in lines if line.startswith("CMD"))
    script = ast.literal_eval(cmd[len("CMD"):].strip())[1]
    in_repo = os.path.join(ROOT, os.path.relpath(workdirs[-1], "/app"), script)
    assert os.path.isfile(in_repo), f"CMD runs {script} from {workdirs[-1]}, which doesn't exist"


def test_dockerignore_keeps_secrets_and_data_out():
    ignore = _read(".dockerignore").decode("utf-8")
    assert "**/.env" in ignore and "*.db" in ignore and "**/venv" in ignore


def test_no_credentials_in_scrapers():
    folder = os.path.join(ROOT, "services", "discovery-agent")
    for dirpath, _, files in os.walk(folder):
        if "venv" in dirpath:
            continue
        for name in files:
            if name.endswith(".py"):
                source = _read(dirpath, name).decode("utf-8")
                assert "__Host-mons" not in source, f"browser cookies in {name}"
                assert not re.search(r"fc-[0-9a-f]{20,}", source), f"Firecrawl key in {name}"
