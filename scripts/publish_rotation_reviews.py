"""Publish an explicitly selected resolved review file for read-only browser restore."""
import argparse,json
from pathlib import Path
from import_rotation_review import validate_review
ROOT=Path(__file__).resolve().parents[1]
def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('resolved',type=Path);args=parser.parse_args()
 demo=ROOT/'data/axel-demo-v1';data=validate_review(json.loads(args.resolved.read_text()),json.loads((demo/'rotation-review-data.json').read_text()))
 target=demo/'rotation-review-saved.json';temp=target.with_suffix('.tmp');temp.write_text(json.dumps(data,ensure_ascii=False,indent=2));temp.replace(target)
 print('Published',len(data['assessments']),'imported reviews; browser storage untouched')
if __name__=='__main__':main()
