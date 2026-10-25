"""Crash-safe local receipt/cursor replacement; never write directly in place."""
import json
import os
from pathlib import Path


def write_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix(path.suffix+'.tmp')
    with temporary.open('w',encoding='utf-8',newline='\n') as output:
        json.dump(value,output,ensure_ascii=False,indent=2,allow_nan=False)
        output.write('\n');output.flush();os.fsync(output.fileno())
    os.replace(temporary,path)
    if os.name!='nt':
        descriptor=os.open(path.parent,os.O_RDONLY)
        try:os.fsync(descriptor)
        finally:os.close(descriptor)
