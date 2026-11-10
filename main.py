"""Standalone LCR 6200 sweep diagnostic (no PI stage required).

Requires meter.py and optionally saver.py / plotter.py in the same folder.
Uses the revised Meter class, whose sweep methods return (mag, phase, timing).
"""
import argparse
from datetime import datetime
from pathlib import Path
import logging
import numpy as np
from meter import Meter


def main():
    parser = argparse.ArgumentParser(description='Test LCR meter without the linear stage')
    parser.add_argument('-p', '--port', required=True, help='LCR serial port, e.g. COM4')
    parser.add_argument('-b', '--baudrate', type=int, default=115200)
    parser.add_argument('--meter-timeout', type=float, default=20.0)
    parser.add_argument('-l', '--level', type=float, default=0.05)
    parser.add_argument('--bias', type=float, nargs='+', default=[0.0])
    parser.add_argument('-a', '--average', type=int, default=1)
    parser.add_argument('-f', '--from', dest='freq_from', type=float, default=1000.0)
    parser.add_argument('-t', '--to', type=float, default=10000.0)
    parser.add_argument('-N', '--count', type=int, default=2, help='Points per decade')
    parser.add_argument('-m', '--mode', choices=['STA', 'LTA'], default='STA')
    parser.add_argument('-s', '--save', default='', help='Experiment name (optional)')
    parser.add_argument('--plot', action=argparse.BooleanOptionalAction, default=False)
    args = parser.parse_args()

    if args.freq_from <= 0 or args.to <= args.freq_from:
        parser.error('Require 0 < --from < --to')
    if args.count < 1 or args.average < 1 or args.meter_timeout <= 0:
        parser.error('--count, --average and --meter-timeout must be positive')
    if args.mode == 'LTA' and len(args.bias) != 1:
        parser.error('LTA supports one bias value only')
    if args.plot and not args.save:
        parser.error('--plot requires --save')

    frequencies = np.logspace(np.log10(args.freq_from), np.log10(args.to),
                              int(round(np.log10(args.to / args.freq_from) * args.count)) + 1)
    outdir = None
    filename = None
    if args.save:
        safe_name = Path(args.save).name
        folder = datetime.now().strftime('%y%m%d_%H%M%S') + '_lcr_only_' + safe_name
        base = Path.cwd() / 'out' / 'data'
        outdir = base / folder
        n = 1
        while outdir.exists():
            outdir = base / f'{folder}_{n}'
            n += 1
        outdir.mkdir(parents=True)
        filename = outdir.name + '.csv'

    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    print('LCR-only diagnostic: no stage connection or motion commands')
    print(f'Port={args.port}, baudrate={args.baudrate}, timeout={args.meter_timeout}s')
    print(f'Frequencies: {frequencies}')
    meter = Meter(port=args.port, baudrate=args.baudrate, timeout=args.meter_timeout)
    try:
        meter.connect()
        print('LCR serial port opened; starting sweep (this does not verify instrument response yet).')
        if args.mode == 'STA':
            if len(args.bias) > 1:
                sweep = meter.sweep_short_time_avg_multi_bias
                bias = args.bias
            else:
                sweep = meter.sweep_short_time_avg
                bias = args.bias[0]
        else:
            sweep = meter.sweep_long_time_avg
            bias = args.bias[0]

        mag, phase, timing = sweep(frequencies=frequencies, level=args.level,
                                   bias=bias, average=args.average)
        print('Sweep completed successfully.')
        print('Magnitude:', mag)
        print('Phase:', phase)
        print('Timing:', timing)

        if outdir is not None:
            import saver
            saver.save_to_csv(frequencies, mag, phase, args.bias, args.mode,
                              args.level, args.average, timing=timing,
                              position=None, outdir=outdir, filename=filename)
            print(f'Saved to: {outdir / filename}')
            if args.plot:
                import plotter
                plotter.make_figure(frequencies, mag, phase, args.bias, outdir=outdir)
    except Exception:
        logging.exception('LCR-only test failed')
        raise
    finally:
        meter.close()
        print('LCR serial port closed.')


if __name__ == '__main__':
    main()
