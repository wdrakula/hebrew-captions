#!/usr/bin/env python3
"""Install this checkout on Linux; no capture, secrets, or API requests."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent

def run(*args, **kwargs):
    subprocess.run(args, check=True, **kwargs)

def missing_packages():
    missing = []
    for binary in ('pactl', 'parec'):
        if shutil.which(binary) is None:
            missing.append('pulseaudio-utils')
    version = f'{sys.version_info.major}.{sys.version_info.minor}'
    # Use matching packages when a non-default Python interpreter was selected.
    try:
        import tkinter
    except ImportError:
        missing.append(f'python{version}-tk')
    if not subprocess.run([sys.executable, '-c', 'import ensurepip'],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
        missing.append(f'python{version}-venv')
    return sorted(set(missing))

def main():
    parser = argparse.ArgumentParser(description='Установка субтитров: окружение, зависимости, ярлык меню.')
    parser.add_argument('--no-menu', action='store_true', help='не создавать ярлык меню')
    parser.add_argument('--skip-system-deps', action='store_true', help='не устанавливать системные пакеты (только проверить)')
    args = parser.parse_args()
    if sys.version_info < (3, 10):
        raise SystemExit('Нужен Python 3.10 или новее.')
    os.chdir(ROOT)
    manifest = json.loads((ROOT/'models/manifest.json').read_text())
    if hashlib.sha256((ROOT/'models/silero_vad.onnx').read_bytes()).hexdigest() != manifest['sha256']:
        raise SystemExit('Контрольная сумма модели Silero не совпадает.')
    packages = missing_packages()
    if packages:
        command = ['apt-get', 'install', '-y', *packages]
        if args.skip_system_deps or not shutil.which('apt-get'):
            raise SystemExit('Нужны системные пакеты: '+', '.join(packages)+'. Установите их пакетным менеджером.')
        if os.geteuid() != 0:
            if not shutil.which('sudo'):
                raise SystemExit('Нужны системные пакеты: '+', '.join(packages)+'. Для автоматической установки требуется sudo.')
            command.insert(0, 'sudo')
        print('Устанавливаю системные пакеты: '+', '.join(packages), flush=True)
        run(*command)
    python = ROOT/'.venv/bin/python'
    if python.exists():
        run(str(python), '-c', 'import sys; raise SystemExit(sys.version_info < (3,10))')
        if Path(sys.executable).resolve() != python.resolve():
            print('Используется уже существующее окружение .venv; оно не заменяется.', flush=True)
    else:
        run(sys.executable, '-m', 'venv', str(ROOT/'.venv'))
    run(str(python), '-m', 'pip', 'install', '-r', str(ROOT/'requirements.txt'))
    run(str(python), '-c', 'import tkinter, numpy, scipy, onnxruntime, websockets; from bidi.algorithm import get_display')
    if not args.no_menu:
        run(str(python), str(ROOT/'install-menu.py'))
    print('\nГотово. Добавьте свой ключ в APIkey.txt рядом с run.sh (одной строкой).')
    print('Запуск: ./run.sh' + ('' if args.no_menu else ' или «Переводчик субтитров» в меню приложений.'))

if __name__ == '__main__':
    try:
        main()
    except subprocess.CalledProcessError as exc:
        raise SystemExit('Установка не завершена: команда вернула ошибку '+str(exc.returncode)) from None
