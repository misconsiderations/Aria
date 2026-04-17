
import sys, os, json, subprocess, shutil

SOURCE_ROOT = os.path.dirname(os.path.abspath(__file__))
TEMP_DIR = os.path.join(SOURCE_ROOT, "hosted_bot_1775847015")
SYNC_DIRS = ("cogs", "core", "static", "utils", "web_ui")
SYNC_FILE_SUFFIXES = (".py", ".json", ".html")
IGNORE_NAMES = {"__pycache__", ".git", ".pytest_cache", ".mypy_cache", "hosted_logs", "dist"}


def _should_copy_root_file(file_name):
    if file_name in {"config.json"}:
        return False
    return file_name.endswith(SYNC_FILE_SUFFIXES)


def _copy_root_files():
    for file_name in os.listdir(SOURCE_ROOT):
        source_path = os.path.join(SOURCE_ROOT, file_name)
        dest_path = os.path.join(TEMP_DIR, file_name)
        if not os.path.isfile(source_path) or not _should_copy_root_file(file_name):
            continue
        try:
            shutil.copy2(source_path, dest_path)
        except Exception:
            pass


def _sync_directory_tree(directory_name):
    source_dir = os.path.join(SOURCE_ROOT, directory_name)
    dest_dir = os.path.join(TEMP_DIR, directory_name)
    if not os.path.isdir(source_dir):
        return
    try:
        shutil.copytree(
            source_dir,
            dest_dir,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
        )
    except Exception:
        pass


def _sync_project_tree():
    os.makedirs(TEMP_DIR, exist_ok=True)
    _copy_root_files()
    for directory_name in SYNC_DIRS:
        _sync_directory_tree(directory_name)
    with open(os.path.join(TEMP_DIR, "config.json"), "w", encoding="utf-8") as config_file:
        json.dump({"token": "REDACTED_DISCORD_TOKEN", "prefix": ";"}, config_file)


_sync_project_tree()

for path in (TEMP_DIR, SOURCE_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

os.chdir(TEMP_DIR)

env = os.environ.copy()
existing_pythonpath = env.get("PYTHONPATH", "")
pythonpath_parts = [TEMP_DIR, SOURCE_ROOT]
if existing_pythonpath:
    pythonpath_parts.append(existing_pythonpath)
env["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)
env["HOSTED_TOKEN"] = "true"
env["HOSTED_UID"] = '1775847015'
env["HOSTED_OWNER_ID"] = '299182971213316107'
env["HOSTED_USER_ID"] = '351719812227137537'
env["HOSTED_USERNAME"] = 'misconsideration'

subprocess.run([sys.executable, os.path.join(TEMP_DIR, "main.py")], cwd=TEMP_DIR, env=env)
