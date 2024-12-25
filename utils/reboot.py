# TODO : return win/linux restart file according to os
import os
import platform

from utils.logger import log


def clear_terminal():
    print('\033[H\033[J')


def get_restart_file(bot_dir, path) -> (str, str):
    os_name = platform.system()
    log.info(f'Running on platform {os_name}')
    if os_name == 'Windows':
        return (
            f"""
@echo off
cd /d "{bot_dir}"
timeout /t 2 /nobreak > nul
python "{path}"
""",
            os_name,
        )
    else:
        return (
            f"""
#!/bin/bash
cd {bot_dir}
sleep 2
python3 {path}
""",
            os_name,
        )


def make_executable(file_path):
    os.chmod(file_path, 0o755)
