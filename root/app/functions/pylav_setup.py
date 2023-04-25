import logging
import pathlib
import os
import shutil
import subprocess
import sys
import json
from typing import Set, Dict, Union

RepoManagerSetting = pathlib.Path("/data/cogs/RepoManager/settings.json")
DownloaderSetting = pathlib.Path("/data/cogs/Downloader/settings.json")
DownloaderLibFolder = pathlib.Path("/data/cogs/Downloader/lib")
RepoManagerRepoFolder = pathlib.Path("/data/cogs/RepoManager/repos/pylav")
CogManagerCogFolder = pathlib.Path("/data/cogs/CogManager/cogs")
CogRepoURL = "https://github.com/PyLav/Red-Cogs"
PyLavHashFile = pathlib.Path("/data/pylav/.hashfile")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)5s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

log = logging.getLogger("PyLavSetup")

STORAGE_TYPE = os.environ.get("STORAGE_TYPE")

if not STORAGE_TYPE:
    with pathlib.Path("/data/config.json").open("r", encoding="utf-8") as __f:
        STORAGE_TYPE = json.load(__f)["docker"]["STORAGE_TYPE"]


IS_JSON = STORAGE_TYPE.upper() == "JSON"

if not IS_JSON:
    RepoManagerRepoFolder = pathlib.Path("/data/pylav/cogs")


def get_git_env() -> Dict[str, str]:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env.pop("GIT_ASKPASS", None)
    env["LC_ALL"] = "C"
    env["LANGUAGE"] = "C"
    return env


def create_or_update_repo_manager_setting() -> None:
    if not RepoManagerSetting.exists():
        log.info("Creating RepoManager setting")
        with RepoManagerSetting.open("w", encoding="utf-8") as f:
            json.dump({"170708480": {"GLOBAL": {"repos": {"pylav": "master"}}}}, f)
    else:
        log.info("Updating RepoManager setting")
        with RepoManagerSetting.open("r", encoding="utf-8") as f:
            exiting_data = json.load(f)
        if "pylav" not in exiting_data["170708480"]["GLOBAL"]["repos"]:
            exiting_data["170708480"]["GLOBAL"]["repos"]["pylav"] = "master"
            with RepoManagerSetting.open("w", encoding="utf-8") as f:
                json.dump(exiting_data, f)


def create_or_update_downloader_setting(data: Dict[str, Dict[str, Union[str, bool]]]) -> None:
    if not DownloaderSetting.exists():
        log.info("Creating Downloader setting")
        with DownloaderSetting.open("w", encoding="utf-8") as f:
            json.dump({"998240343": {"GLOBAL": {"installed_cogs": {"pylav": data}}}}, f)
    else:
        log.info("Updating Downloader setting")
        with DownloaderSetting.open("r", encoding="utf-8") as f:
            exiting_data = json.load(f)
        exiting_data["998240343"]["GLOBAL"]["installed_cogs"]["pylav"] = data
        with DownloaderSetting.open("w", encoding="utf-8") as f:
            json.dump(exiting_data, f)


def clone_or_update_pylav_repo() -> str:
    env = get_git_env()
    if (RepoManagerRepoFolder / ".git").exists():
        log.info("Updating PyLav repo")
        subprocess.call(["git", "reset", "--hard", "HEAD", "-q"], cwd=RepoManagerRepoFolder, env=env)
        subprocess.call(["git", "clean", "-f", "-d", "-q"], cwd=RepoManagerRepoFolder, env=env)
        subprocess.call(["git", "pull", "-q", "--rebase", "--autostash"], cwd=RepoManagerRepoFolder, env=env)
    else:
        log.info("Cloning PyLav repo")
        subprocess.call(["git", "clone", CogRepoURL, RepoManagerRepoFolder], cwd=RepoManagerRepoFolder, env=env)
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=RepoManagerRepoFolder, env=env).decode().strip()


def get_pylav_cogs() -> Dict[str, pathlib.Path]:
    return {
        cog.name: cog
        for cog in RepoManagerRepoFolder.iterdir()
        if cog.is_dir() and (cog.name.startswith("pl") or cog.name == "audio")
    }


def copy_and_overwrite(from_path: Union[str, os.PathLike[str]], to_path: Union[str, os.PathLike[str]]) -> None:
    if os.path.exists(to_path):
        shutil.rmtree(to_path)
    log.info("Copying %s to %s", from_path, to_path)
    shutil.copytree(from_path, to_path)


def install_or_update_pylav_cogs(cogs: Dict[str, pathlib.Path]) -> None:
    for cog in cogs.values():
        copy_and_overwrite(cog, CogManagerCogFolder / cog.name)


def get_requirements_for_all_cogs(cogs: Dict[str, pathlib.Path]) -> Set[str]:
    requirements = set()
    for cog in cogs.values():
        if (cog / "info.json").exists():
            with (cog / "info.json").open("r", encoding="utf-8") as f:
                data = json.load(f)
            if "requirements" in data:
                for req in data["requirements"]:
                    requirements.add(req)
    return requirements


def install_requirements(cogs: Dict[str, pathlib.Path]) -> None | subprocess.Popen[str]:
    if requirements := get_requirements_for_all_cogs(cogs):
        log.info("Installing requirements: %s", requirements)
        proc = subprocess.Popen(
            [
                "/data/venv/bin/pip",
                "install",
                "--upgrade",
                "--no-input",
                "--no-warn-conflicts",
                "--require-virtualenv",
                "--upgrade-strategy",
                "eager",
                "--target",
                DownloaderLibFolder,
                *requirements,
            ],
            env=get_git_env(),
            stdout=subprocess.PIPE,
            universal_newlines=True,
        )
        while True:
            line = proc.stdout.readline()
            if not line:
                break
            log.info(line.strip("\n"))
            if line.startswith("Successfully installed"):
                break
        return proc
    log.info("Requirements installed")


def generate_updated_downloader_setting(
    cogs: Dict[str, pathlib.Path], commit_hash: str
) -> Dict[str, Dict[str, Union[str, bool]]]:
    return {
        cog.name: {
            "repo_name": "pylav",
            "module_name": cog.name,
            "commit": commit_hash,
            "pinned": True,
        }
        for cog in cogs.values()
    }


def get_existing_commit() -> str:
    if PyLavHashFile.exists():
        with PyLavHashFile.open("r", encoding="utf-8") as f:
            return f.read()
    return ""


def update_existing_commit(commit_hash: str) -> None:
    with PyLavHashFile.open("w", encoding="utf-8") as f:
        f.write(commit_hash)


if __name__ == "__main__":
    if (PCX_DISCORDBOT_TAG := os.getenv("PCX_DISCORDBOT_TAG")) is None or "pylav" not in PCX_DISCORDBOT_TAG:
        # This script was called outside a docker container or the docker container is not a pylav image
        log.info("Skipping PyLav setup and update")
        sys.exit(0)
    for folder in (DownloaderLibFolder, RepoManagerRepoFolder, CogManagerCogFolder):
        if not folder.exists():
            folder.mkdir(parents=True, mode=0o776)
    current_commit = clone_or_update_pylav_repo()
    existing_commit = get_existing_commit()
    cogs_mapping = get_pylav_cogs()
    if current_commit == existing_commit:
        log.info("PyLav is up to date")
        sys.exit(0)
    else:
        if IS_JSON:
            install_or_update_pylav_cogs(cogs_mapping)
        process = install_requirements(cogs_mapping)
    try:
        log.info("Current PyLav-Cogs Commit: %s", current_commit)
        downloader_data = generate_updated_downloader_setting(cogs_mapping, current_commit)
        log.info("Updated Downloader Data: %s", downloader_data)
        if IS_JSON:
            create_or_update_downloader_setting(downloader_data)
            create_or_update_repo_manager_setting()
        update_existing_commit(current_commit)
        if process is not None:
            log.info("Waiting for requirements to finish installing")
            process.wait()
        log.info("PyLav setup and update finished")
    except Exception as e:
        log.info("PyLav setup and update failed: %s", e, exc_info=e)
    finally:
        if process is not None:
            process.kill()
            process.terminate()
        sys.exit(0)
