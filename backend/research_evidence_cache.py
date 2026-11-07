"""Small atomic cache of source evidence; callers must revalidate its dates."""
import json
import os
import tempfile
import threading
from pathlib import Path

_lock=threading.RLock()


def load_record(path,key):
    try:
        with _lock:
            path=Path(path)
            if path.stat().st_size>8_000_000:return None
            data=json.loads(path.read_text(encoding='utf-8'))
        return data.get('records',{}).get(key) if data.get('version')==1 else None
    except (OSError,ValueError,AttributeError,TypeError):return None


def save_record(path,key,record):
    path=Path(path);temporary=None
    try:
        with _lock:
            try:
                data=json.loads(path.read_text(encoding='utf-8'))
                records=data['records'] if data.get('version')==1 and isinstance(data.get('records'),dict) else {}
            except (OSError,ValueError,AttributeError,TypeError):records={}
            records[key]=record
            text=json.dumps({'version':1,'records':records},ensure_ascii=False)
            if len(text.encode('utf-8'))>8_000_000:return
            path.parent.mkdir(parents=True,exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,prefix=path.name+'.',suffix='.tmp',delete=False) as output:
                temporary=Path(output.name);output.write(text)
            os.replace(temporary,path);temporary=None
    except OSError:pass
    finally:
        if temporary is not None:
            try:temporary.unlink()
            except OSError:pass
