"""Stage-positioned LCR sweeps using the revised meter.py.

Requires: meter.py (returns magnitude, phase, timing), saver.py, plotter.py,
          numpy, pyserial, and pipython.

This is a step-and-measure script, NOT continuous acquisition during motion.
"""
import argparse
import logging
import time
from datetime import datetime
from pathlib import Path

import numpy as np
from meter import Meter
from pipython import GCSDevice, pitools

LOG = logging.getLogger('stage_lcr')


def arguments():
    p = argparse.ArgumentParser(description='Step stage and measure LCR impedance sweeps.')
    p.add_argument('-p', '--port', required=True, help='LCR serial port, e.g. COM4')
    p.add_argument('-b', '--baudrate', type=int, default=115200)
    p.add_argument('--meter-timeout', type=float, default=20.0,
                   help='LCR response timeout in seconds (default: 20)')
    p.add_argument('--stage', type=int, default=3, help='PI C-863 RS232 COM number')
    p.add_argument('--stage-baudrate', type=int, default=115200)
    p.add_argument('--settle', type=float, default=2.0,
                   help='Seconds to wait after each completed stage movement')
    p.add_argument('--positions', type=float, nargs='+', default=[0.1, 0.2])
    p.add_argument('-s', '--save', default='', help='Experiment name (optional)')
    p.add_argument('-l', '--level', type=float, default=0.05)
    p.add_argument('--bias', type=float, nargs='+', default=[0.0])
    p.add_argument('-a', '--average', type=int, default=1)
    p.add_argument('-f', '--from', dest='freq_from', type=float, default=10.0)
    p.add_argument('-t', '--to', dest='freq_to', type=float, default=200000.0)
    p.add_argument('-N', '--count', type=int, default=7)
    p.add_argument('-m', '--mode', choices=['STA', 'LTA'], default='STA')
    p.add_argument('--plot', action=argparse.BooleanOptionalAction, default=False)
    return p.parse_args()


def make_output_folder(name):
    if not name:
        return None, None
    base = Path.cwd() / 'out' / 'data'
    stem = f'{datetime.now():%y%m%d_%H%M%S}_sweep_{Path(name).name}'
    directory = base / stem
    index = 1
    while directory.exists():
        directory = base / f'{stem}_{index}'
        index += 1
    directory.mkdir(parents=True)
    return directory, directory.name + '.csv'


def validate(args):
    if not (0 < args.freq_from < args.freq_to):
        raise ValueError('Require 0 < --from < --to')
    if args.count < 1 or args.average < 1:
        raise ValueError('--count and --average must be >= 1')
    if args.meter_timeout <= 0 or args.settle < 0:
        raise ValueError('Timeout must be positive; settling time nonnegative')
    if not args.positions or not all(np.isfinite(x) for x in args.positions):
        raise ValueError('All positions must be finite numbers')
    if not all(np.isfinite(x) for x in args.bias):
        raise ValueError('Bias values must be finite')
    if args.mode == 'LTA' and len(args.bias) != 1:
        raise ValueError('LTA supports exactly one bias')
    # Normalize COM3, com3, and 3 to the same comparison key.
    meter_port = str(args.port).strip().upper()
    stage_port = f'COM{args.stage}'
    if meter_port == stage_port or meter_port == str(args.stage):
        raise ValueError(f'LCR and stage cannot both use {stage_port}')


def main():
    args = arguments()
    validate(args)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    total_points = int(round(np.log10(args.freq_to / args.freq_from) * args.count)) + 1
    frequencies = np.logspace(np.log10(args.freq_from), np.log10(args.freq_to), total_points)
    directory, filename = make_output_folder(args.save)
    print(f'Experiment directory: {directory or "not saving to a named experiment folder"}')
    print(f'LCR port={args.port}; stage=COM{args.stage}; frequency points={len(frequencies)}')

    # Initialize/reference the stage BEFORE opening the meter's serial port.
    # Do not assume that the LCR is connected until this setup has finished.
    with GCSDevice('C-863') as stage:
        stage.ConnectRS232(comport=args.stage, baudrate=args.stage_baudrate)
        axis = stage.axes[0]
        print('Stage:', stage.qIDN().strip())
        print('Referencing stage using FNL; verify clearance and travel before proceeding.')
        pitools.startup(stage, stages=['M-112.1DG'], refmodes=['FNL'])

        # Reject out-of-travel positions where controller limits can be read.
        low = stage.qTMN(axis)[axis]
        high = stage.qTMX(axis)[axis]
        for target in args.positions:
            if not low <= target <= high:
                raise ValueError(f'Target {target} mm outside stage limits [{low}, {high}] mm')

        meter = Meter(port=args.port, baudrate=args.baudrate, timeout=args.meter_timeout)
        try:
            meter.connect()
            print(f'LCR port opened: {args.port}')
            if args.mode == 'STA':
                if len(args.bias) > 1:
                    fn = meter.sweep_short_time_avg_multi_bias
                    bias = args.bias
                else:
                    fn = meter.sweep_short_time_avg
                    bias = args.bias[0]
            else:
                fn = meter.sweep_long_time_avg
                bias = args.bias[0]

            for i, target in enumerate(args.positions, 1):
                print(f'\n[{i}/{len(args.positions)}] Moving to {target:.6f} mm')
                stage.MOV(axis, target)
                pitools.waitontarget(stage, axes=axis)
                position = stage.qPOS(axis)[axis]
                print(f'Stage at {position:.6f} mm; settling {args.settle:g} s')
                time.sleep(args.settle)

                print('Starting LCR sweep (no *IDN? debug command)')
                # Fail fast on communication errors: do not silently repeat triggers.
                mag, phase, timing = fn(
                    frequencies=frequencies, level=args.level,
                    bias=bias, average=args.average
                )
                if directory is not None:
                    import saver
                    saver.save_to_csv(
                        frequencies, mag, phase, args.bias, args.mode,
                        args.level, args.average, timing=timing,
                        position=position, outdir=directory, filename=filename
                    )
                    print('Saved:', directory / filename)
                else:
                    print('No --save specified; no CSV written by this script.')

                if args.plot:
                    if directory is None:
                        LOG.warning('--plot requested without --save; skipping plot')
                    else:
                        import plotter
                        plotter.make_figure(
                            frequencies, mag, phase, args.bias,
                            outdir=directory, position=position
                        )
                print(f'Completed measurement at {position:.6f} mm')
        except Exception:
            LOG.exception('Experiment aborted. Check the last stage position and LCR response.')
            # Best effort only; STP behavior must be verified for your controller.
            try:
                stage.STP()
            except Exception:
                LOG.exception('Could not issue stage stop command')
            raise
        finally:
            meter.close()
            print('LCR serial connection closed.')

    print('\nAll position sweeps completed.')


if __name__ == '__main__':
    main()
