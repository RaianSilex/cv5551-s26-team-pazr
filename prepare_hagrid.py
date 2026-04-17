import argparse, os, subprocess, yaml
from pathlib import Path

TARGET_GESTURES = ['one', 'peace', 'four', 'three', 'ok', 'fist']

GESTURE_ROLE = {
    'one':   'coffee',
    'peace': 'orange_juice',
    'three':  'chocolate',
    'four': 'lactose_free_toggle',
    'ok':    'confirm',
    'fist':  'cancel',
}


def run(cmd, **kwargs):
    print(f'$ {cmd}')
    subprocess.run(cmd, shell=True, check=True, **kwargs)


def download_hagrid(save_path: Path, subset: bool):
    targets = ' '.join(TARGET_GESTURES)
    flags = '--train --annotations'
    if subset:
        flags += ' --subset'
        print(f'Downloading SUBSET (100 imgs/class) for: {TARGET_GESTURES}')
    else:
        print(f'Downloading FULL dataset for: {TARGET_GESTURES}')
        print('Note: ~38 GB per class — make sure you have ~230 GB free.')

    run(
        f'python download.py '
        f'--save_path {save_path} '
        f'-t {targets} '
        f'{flags} '
        f'--dataset'
    )


def convert_to_yolo(save_path: Path, output_path: Path):

    cfg = {
        'dataset': {
            'annotations': str(save_path / 'hagrid_annotations' / 'train'),
            'dataset':     str(save_path),
        },
        'target_classes': TARGET_GESTURES,
        'output': str(output_path),
        'num_workers': 4,
    }
    cfg_path = save_path / 'convert_cfg.yaml'
    with open(cfg_path, 'w') as f:
        yaml.dump(cfg, f)

    print('Converting annotations to YOLO format...')
    run(f'python -m converters.hagrid_to_yolo --cfg {cfg_path} --mode gestures')


def write_dataset_yaml(output_path: Path):
    class_names = TARGET_GESTURES 

    dataset_yaml = {
        'path': str(output_path),
        'train': 'images/train',
        'val':   'images/val',
        'nc':    len(class_names),
        'names': class_names,
    }
    out = output_path / 'dataset.yaml'
    with open(out, 'w') as f:
        yaml.dump(dataset_yaml, f, default_flow_style=False)
    print(f'dataset.yaml written to {out}')
    print(f'Class mapping:')
    for i, name in enumerate(class_names):
        print(f'  {i}: {name:8s} → {GESTURE_ROLE[name]}')
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--save_path',  default='./hagrid_data',  help='Where to save downloaded data')
    parser.add_argument('--output',     default='./yolo_dataset', help='Where to write YOLO-format data')
    parser.add_argument('--subset',     action='store_true',       help='Download 100-image subset only (for testing)')
    parser.add_argument('--skip_download', action='store_true',    help='Skip download (already done), just convert')
    args = parser.parse_args()

    save_path   = Path(args.save_path)
    output_path = Path(args.output)
    save_path.mkdir(parents=True, exist_ok=True)
    output_path.mkdir(parents=True, exist_ok=True)

    if not args.skip_download:
        download_hagrid(save_path, args.subset)

    convert_to_yolo(save_path, output_path)
    yaml_path = write_dataset_yaml(output_path)

    print(f'\nDone! Next step — train:')
    print(f'    python train_gesture_yolo.py --data {yaml_path}')


if __name__ == '__main__':
    main()
