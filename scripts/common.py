from pathlib import Path
from datetime import datetime, timezone
import json
ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data"
CONFIG=json.loads((ROOT/"config.json").read_text())
def load_json(p,d):
    try:return json.loads(p.read_text())
    except:return d
def save_json(p,o):p.write_text(json.dumps(o,indent=2,allow_nan=False))
def now_iso():return datetime.now(timezone.utc).isoformat()
