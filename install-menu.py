#!/usr/bin/env python3
"""Install a desktop entry for this checkout without hard-coded home paths."""
from pathlib import Path
import os

root=Path(__file__).resolve().parent
# Escape Desktop Entry string values and Exec arguments independently.
def value(text):
    return str(text).replace('\\','\\\\').replace('\n','\\n').replace('\r','\\r').replace('\t','\\t')
def argument(text):
    escaped=str(text).replace('\\','\\\\').replace('"','\\"').replace('`','\\`').replace('$','\\$').replace('%','%%')
    return value('"'+escaped+'"')
base=Path(os.environ.get('XDG_DATA_HOME',Path.home()/'.local/share'))
destination=base/'applications/hebrew-captions.desktop'
destination.parent.mkdir(parents=True,exist_ok=True)
destination.write_text('[Desktop Entry]\nType=Application\nName=Иврит → русский\n'
    'Comment=Системные субтитры с историей\nExec='+argument(root/'run.sh')+'\nPath='+value(root)+
    '\nIcon=audio-input-microphone\nTerminal=false\nCategories=AudioVideo;Accessibility;\nStartupNotify=false\n')
print('Ярлык установлен:',destination)
