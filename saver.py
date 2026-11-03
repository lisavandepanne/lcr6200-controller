
import csv
import datetime
from pathlib import Path
import numpy as np


def save_to_csv(
    frequencies,
    mag,
    phase,
    bias_list,
    mode="STA",
    level=0.05,
    average=1,
    outdir=None,
    title=None,
    timing=None,
    position=None,
    filename=None,
):
    if outdir is None:
        return

    if timing is None:
        raise ValueError("Timing data is required to save timestamps.")

    if filename is None:
        raise ValueError(
            "A filename must be provided so all positions "
            "are saved to the same CSV file."
        )

    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    # Ensure the filename has a .csv extension
    filename = Path(filename).name
    if not filename.lower().endswith(".csv"):
        filename += ".csv"

    filepath = outdir / filename

    # Check whether the CSV already contains data
    write_header = (
        not filepath.exists()
        or filepath.stat().st_size == 0
    )

    # Support single-bias and multi-bias measurements
    mag_list = mag if len(bias_list) > 1 else [mag]
    phase_list = phase if len(bias_list) > 1 else [phase]
    timing_list = timing if len(bias_list) > 1 else [timing]

    # Append measurements from each stage position
    with open(filepath, mode="a", newline="") as f:
        writer = csv.writer(f)

        # Write header only once
        if write_header:
            writer.writerow([
                "Mode",
                "Level (V)",
                "Average",
                "Bias (V)",
                "Frequency (Hz)",
                "Sample Index",
                "Magnitude",
                "Phase (deg)",
                "Trigger Datetime",
                "Arrival Datetime",
                "Duration (ms)",
                "Position (mm)",
            ])

        for b_idx, b_val in enumerate(bias_list):
            m_matrix = np.asarray(mag_list[b_idx])
            p_matrix = np.asarray(phase_list[b_idx])
            t_matrix = np.asarray(timing_list[b_idx])

            num_freqs, num_samples = m_matrix.shape

            if p_matrix.shape != (num_freqs, num_samples):
                raise ValueError(
                    "Phase shape does not match magnitude."
                )

            if t_matrix.shape != (num_freqs, num_samples, 2):
                raise ValueError(
                    "Timing must have shape "
                    "(frequencies, samples, 2)."
                )

            if len(frequencies) != num_freqs:
                raise ValueError(
                    "Frequency count does not match magnitude."
                )

            for f_idx in range(num_freqs):
                freq = frequencies[f_idx]

                for s_idx in range(num_samples):
                    # ISO datetime strings from meter.py
                    t_trigger = str(
                        t_matrix[f_idx, s_idx, 0]
                    )
                    t_arrival = str(
                        t_matrix[f_idx, s_idx, 1]
                    )

                    trigger_dt = datetime.datetime.fromisoformat(
                        t_trigger
                    )
                    arrival_dt = datetime.datetime.fromisoformat(
                        t_arrival
                    )

                    # Calculate measurement duration in ms
                    duration_ms = (
                        arrival_dt - trigger_dt
                    ).total_seconds() * 1000

                    writer.writerow([
                        mode,
                        level,
                        average,
                        b_val,
                        freq,
                        s_idx,
                        m_matrix[f_idx, s_idx],
                        p_matrix[f_idx, s_idx],
                        t_trigger,
                        t_arrival,
                        duration_ms,
                        position,
                    ])

    print(f"Data saved to: {filepath}")
