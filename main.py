
import argparse
from meter import Meter
import numpy as np
import plotter
import saver
from pathlib import Path
from pipython import GCSDevice, pitools
from datetime import datetime


if __name__ == "__main__":

    parser = argparse.ArgumentParser(
        description="Run a frequency sweep using the LCR 6200 device."
    )

    # Connection arguments
    parser.add_argument(
        "-p",
        "--port",
        required=True,
        help="Serial port connected to the meter (e.g., COM3 or /dev/ttyUSB0)",
    )

    parser.add_argument(
        "-b",
        "--baudrate",
        type=int,
        default=115200,
        help="Serial baudrate (default: 115200)",
    )

    parser.add_argument(
        "-s",
        "--save",
        type=str,
        default="",
        help="Experiment name. If provided, save data in a new experiment folder.",
    )

    # Measurement configuration arguments
    parser.add_argument(
        "-l",
        "--level",
        type=float,
        default=0.05,
        help="Stimulus voltage level in volts (default: 0.05)",
    )

    parser.add_argument(
        "--bias",
        type=float,
        nargs="+",
        default=[0.0],
        help="Bias voltage in volts (default: [0.0])"
    )

    parser.add_argument(
        "-a",
        "--average",
        type=int,
        default=1,
        help="Number of samples to average per frequency (default: 1)",
    )

    # Frequency sweep options
    parser.add_argument(
        "-f",
        "--from",
        dest="freq_from",
        type=float,
        default=10,
        help="Minimum frequency value in the sweep",
    )

    parser.add_argument(
        "-t",
        "--to",
        type=float,
        default=200000,
        help="Maximum frequency value in the sweep",
    )

    parser.add_argument(
        "-N",
        "--count",
        type=int,
        default=7,
        help="Frequencies per decade",
    )

    parser.add_argument(
        "-m",
        "--mode",
        default="STA",
        choices=["STA", "LTA"],
        help="Select Mode",
    )

    parser.add_argument(
        "--positions",
        type=float,
        nargs="+",
        default=[0.1, 0.2],
        help="Absolute stage positions in mm"
    )

    parser.add_argument(
        "--stage",
        type=int,
        default=3,
        help="Port of the PI stage controller"
    )

    args = parser.parse_args()

    # ==========================================================
    # CREATE ONE FOLDER AND ONE CSV PER EXPERIMENT
    # ==========================================================

    experiment_dir = None
    experiment_filename = None

    if args.save:

        # Generate timestamp
        timestamp = datetime.now().strftime("%y%m%d_%H%M%S")

        # Experiment name
        experiment_name = Path(args.save).name

        # Base output directory
        base_dir = Path.cwd() / "out" / "data"

        # Folder name
        folder_name = f"{timestamp}_sweep_{experiment_name}"

        # Create unique experiment folder
        experiment_dir = base_dir / folder_name

        suffix = 1

        while experiment_dir.exists():
            experiment_dir = base_dir / f"{folder_name}_{suffix}"
            suffix += 1

        experiment_dir.mkdir(
            parents=True,
            exist_ok=False
        )

        # ONE CSV filename for the entire experiment
        experiment_filename = (
            experiment_dir.name + ".csv"
        )

        print("\n--- Experiment Created ---")
        print(f"Folder: {experiment_dir}")
        print(f"CSV file: {experiment_filename}")

    # ==========================================================
    # FREQUENCY CONFIGURATION
    # ==========================================================

    f_min = args.freq_from
    f_max = args.to
    N = args.count

    if f_min <= 0 or f_max <= f_min:
        raise ValueError(
            "Frequency limits must satisfy 0 < freq_from < freq_to."
        )

    if N <= 0:
        raise ValueError(
            "Frequencies per decade must be positive."
        )

    # Calculate total decades and total number of points
    num_decades = np.log10(f_max / f_min)

    total_points = int(round(num_decades * N)) + 1

    # Generate log-spaced frequencies
    frequencies = np.logspace(
        np.log10(f_min),
        np.log10(f_max),
        num=total_points
    )

    # ==========================================================
    # INITIALIZE METER
    # ==========================================================

    meter = Meter(
        port=args.port,
        baudrate=args.baudrate
    )

    meter.connect()

    print(
        f"Connected to {args.port} at {args.baudrate} baud."
    )

    # Select measurement function
    if args.mode == "STA":

        if len(args.bias) > 1:

            fn = meter.sweep_short_time_avg_multi_bias
            bias = args.bias

        else:

            fn = meter.sweep_short_time_avg
            bias = args.bias[0]

    elif args.mode == "LTA":

        if len(args.bias) != 1:
            raise ValueError(
                "LTA currently supports one bias value."
            )

        fn = meter.sweep_long_time_avg
        bias = args.bias[0]

    # ==========================================================
    # STAGE CONFIGURATION
    # ==========================================================

    CONTROLLERNAME = "C-863"
    STAGES = ["M-112.1DG"]
    REFMODES = ["FNL"]

    # Connect to stage
    with GCSDevice(CONTROLLERNAME) as stage:

        stage.ConnectRS232(
            comport=args.stage,
            baudrate=115200
        )

        axis = stage.axes[0]

        print(
            f"Connected to stage: {stage.qIDN().strip()}"
        )

        print("Initialize connected stages...")

        pitools.startup(
            stage,
            stages=STAGES,
            refmodes=REFMODES
        )

        # ======================================================
        # LOOP OVER STAGE POSITIONS
        # ======================================================

        for target in args.positions:

            print(
                f"\n--- Moving stage to {target:.4f} mm ---"
            )

            # Move to absolute position
            stage.MOV(axis, target)

            # Wait until target reached
            pitools.waitontarget(
                stage,
                axes=axis
            )

            # Read actual position
            position = stage.qPOS(axis)[axis]

            print(
                f"Stage stopped at {position:.6f} mm"
            )

            # ==================================================
            # PERFORM EIS MEASUREMENT
            # ==================================================

            print(
                f"Running sweep at {position:.6f} mm..."
            )

            mag, phase, timing = fn(
                frequencies=frequencies,
                level=args.level,
                bias=bias,
                average=args.average,
            )

            # ==================================================
            # APPEND DATA TO THE SAME EXPERIMENT CSV
            # ==================================================

            saver.save_to_csv(
                frequencies,
                mag,
                phase,
                args.bias,
                args.mode,
                args.level,
                args.average,
                timing=timing,
                position=position,
                outdir=experiment_dir,
                filename=experiment_filename,
            )

            # Every stage position uses the SAME filename.
            # saver.py uses append mode ("a"), so measurements
            # from all heights are added to one CSV file.

            # ==================================================
            # OPTIONAL: SAVE PLOTS
            # ==================================================

            # Uncomment to save plots in the experiment folder.
            #
            # if experiment_dir is not None:
            #
            #     plotter.make_figure(
            #         frequencies,
            #         mag,
            #         phase,
            #         args.bias,
            #         outdir=experiment_dir,
            #         position=position
            #     )

            print(
                f"Completed measurement at {position:.6f} mm"
            )

    # ==========================================================
    # EXPERIMENT COMPLETE
    # ==========================================================

    print("\n--- All Position Sweeps Complete ---")

    if experiment_dir is not None:

        print("\n--- Experiment Data Saved ---")

        print(
            f"Folder: {experiment_dir}"
        )

        print(
            f"CSV: {experiment_dir / experiment_filename}"
        )
